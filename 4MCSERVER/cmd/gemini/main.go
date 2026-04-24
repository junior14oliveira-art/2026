package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"syscall"
	"time"

	"4mcserver/internal/dhcp"
	"4mcserver/internal/tftp"
)

// ─────────────────────────────────────────────
// Tipos e Estruturas de Dados
// ─────────────────────────────────────────────

type ISOEntry struct {
	Name    string `json:"name"`
	Size    int64  `json:"size"`
	SizeMB  string `json:"size_mb"`
	Type    string `json:"iso_type"`
	Path    string `json:"path"`
	Ready   bool   `json:"ready"`
	Status  string `json:"status"` // "none", "extracting", "ready", "error"
	Key     string `json:"key"`
}

type GlobalState struct {
	Running    bool   `json:"running"`
	SelectedIP string `json:"selected_ip"`
}

// ─────────────────────────────────────────────
// Estado Global e Mutexes
// ─────────────────────────────────────────────

var (
	state      = GlobalState{}
	dhcpServer *dhcp.Server
	tftpServer *tftp.Server
	mu         sync.Mutex
	isoList    []ISOEntry
	isoMu      sync.Mutex
)

const isoFolder = "./iso"

// ─────────────────────────────────────────────
// Captura de Logs para o Painel Web
// ─────────────────────────────────────────────

type LogCapture struct {
	mu   sync.Mutex
	logs []string
}

func (l *LogCapture) Write(p []byte) (n int, err error) {
	msg := string(p)
	os.Stdout.WriteString(msg)
	l.mu.Lock()
	l.logs = append(l.logs, strings.TrimRight(msg, "\n"))
	if len(l.logs) > 150 {
		l.logs = l.logs[1:]
	}
	l.mu.Unlock()
	return len(p), nil
}

var logCatcher = &LogCapture{}

// ─────────────────────────────────────────────
// Middlewares e Wrappers HTTP
// ─────────────────────────────────────────────

type responseWriter struct {
	http.ResponseWriter
	status      int
	wroteHeader bool
}

func (rw *responseWriter) WriteHeader(code int) {
	if rw.wroteHeader {
		return
	}
	rw.status = code
	rw.wroteHeader = true
	rw.ResponseWriter.WriteHeader(code)
}

// ─────────────────────────────────────────────
// Ponto de Entrada (Main)
// ─────────────────────────────────────────────

func main() {
	log.SetOutput(logCatcher)
	log.Println(" ================================================================")
	log.Println("   4MCSERVER v2.0.3  |  Ultra PXE Engine  |  Powered by Go")
	log.Println(" ================================================================")

	os.MkdirAll(isoFolder, 0755)
	os.MkdirAll("./data/extracted", 0755)

	// Scan inicial da biblioteca
	count := scanISOFolder()
	log.Printf("[SISTEMA] %d ISO(s) detectada(s) na inicialização", count)

	go watchISOs()

	mux := http.NewServeMux()

	// Registro de Handlers de API
	mux.HandleFunc("/api/status", handleStatus)
	mux.HandleFunc("/api/logs", handleLogs)
	mux.HandleFunc("/api/start", handleStart)
	mux.HandleFunc("/api/stop", handleStop)
	mux.HandleFunc("/api/isos", handleISOs)
	mux.HandleFunc("/api/isos/scan", handleISOScan)
	mux.HandleFunc("/api/isos/add", handleISOAdd)
	mux.HandleFunc("/api/isos/remove", handleISORemove)
	mux.HandleFunc("/api/isos/browse", handleISOBrowse)
	mux.HandleFunc("/api/isos/prepare", handleISOPrepare)
	mux.HandleFunc("/api/network/interfaces", handleNetInterfaces)
	mux.HandleFunc("/api/network/select", handleNetSelect)
	mux.HandleFunc("/menu.ipxe", handleMenu)

	// Servidores de Arquivos Estáticos e Virtuais
	mux.Handle("/virtual/", http.StripPrefix("/virtual/", http.FileServer(http.Dir("./data/extracted"))))
	mux.Handle("/iso/", http.StripPrefix("/iso/", http.FileServer(http.Dir("./iso"))))
	mux.Handle("/boot/", http.StripPrefix("/boot/", http.FileServer(http.Dir("./boot"))))
	mux.Handle("/", http.FileServer(http.Dir("./static")))

	// Middleware de Log Detalhado
	wrappedMux := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		rw := &responseWriter{ResponseWriter: w, status: 200}
		mux.ServeHTTP(rw, r)
		if r.URL.Path != "/api/logs" && r.URL.Path != "/api/status" {
			log.Printf("[HTTP] %s %s -> %d", r.Method, r.URL.Path, rw.status)
		}
	})

	log.Println("[INFO] Dashboard 4MCSERVER disponível em http://localhost:8080")
	
	go func() {
		if err := http.ListenAndServe(":8080", wrappedMux); err != nil {
			log.Fatalf("[FATAL] Erro no servidor web: %v", err)
		}
	}()

	// Graceful Shutdown
	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)
	<-sigs
	log.Println("[INFO] Encerrando serviços do 4MCSERVER...")
	if dhcpServer != nil {
		dhcpServer.Stop()
	}
	log.Println("[INFO] Bye!")
}

// ─────────────────────────────────────────────
// Implementação dos Handlers
// ─────────────────────────────────────────────

func handleStatus(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	mu.Lock()
	defer mu.Unlock()
	json.NewEncoder(w).Encode(state)
}

func handleLogs(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	logCatcher.mu.Lock()
	defer logCatcher.mu.Unlock()
	json.NewEncoder(w).Encode(logCatcher.logs)
}

func handleStart(w http.ResponseWriter, r *http.Request) {
	if w != nil { w.Header().Set("Content-Type", "application/json") }
	mu.Lock()
	defer mu.Unlock()
	
	// Se já estiver rodando, para primeiro (permite restart com novo IP)
	if dhcpServer != nil { dhcpServer.Stop(); dhcpServer = nil }
	if tftpServer != nil { tftpServer.Stop(); tftpServer = nil }

	listenIP := state.SelectedIP
	if listenIP == "" {
		listenIP = "0.0.0.0"
	}

		// Motor DHCP
		dhcpSrv := dhcp.NewServer(listenIP)
		if err := dhcpSrv.Listen(); err != nil {
			log.Printf("[ERRO] Falha DHCP: %v", err)
			http.Error(w, err.Error(), 500)
			return
		}
		dhcpServer = dhcpSrv

		// Motor TFTP
		bootDir := "./boot"
		os.MkdirAll(bootDir, 0755)
		tftpSrv := tftp.NewServer(listenIP, bootDir)
		if err := tftpSrv.Listen(); err != nil {
			log.Printf("[ERRO] Falha TFTP: %v", err)
		}
		tftpServer = tftpSrv

		state.Running = true
		log.Printf("[SERVIÇOS] Servidores ATIVOS na interface %s", listenIP)
	
	if w != nil { json.NewEncoder(w).Encode(map[string]string{"status": "started"}) }
}

func handleStop(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	mu.Lock()
	defer mu.Unlock()
	if state.Running {
		if dhcpServer != nil {
			dhcpServer.Stop()
			dhcpServer = nil
		}
		if tftpServer != nil {
			tftpServer.Stop()
			tftpServer = nil
		}
		state.Running = false
		log.Println("[SERVIÇOS] Servidores parados com sucesso")
	}
	json.NewEncoder(w).Encode(map[string]string{"status": "stopped"})
}

func handleISOs(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	isoMu.Lock()
	defer isoMu.Unlock()
	json.NewEncoder(w).Encode(isoList)
}

func handleISOScan(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	count := scanISOFolder()
	json.NewEncoder(w).Encode(map[string]interface{}{"found": count})
}

func handleISOAdd(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	var body struct{ Path string `json:"path"` }
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Path == "" {
		http.Error(w, "JSON inválido", 400)
		return
	}
	entry, err := addISO(body.Path)
	if err != nil {
		http.Error(w, err.Error(), 400)
		return
	}
	json.NewEncoder(w).Encode(entry)
}

func handleISORemove(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	name := r.URL.Query().Get("name")
	isoMu.Lock()
	defer isoMu.Unlock()
	newList := []ISOEntry{}
	for _, iso := range isoList {
		if iso.Name != name {
			newList = append(newList, iso)
		}
	}
	isoList = newList
	json.NewEncoder(w).Encode(map[string]bool{"success": true})
}

func handleISOBrowse(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	found := []map[string]string{}
	// Escaneia drives de C: a Z:
	for _, letter := range "CDEFGHIJKLMNOPQRSTUVWXYZ" {
		root := string(letter) + `:\`
		if _, err := os.Stat(root); err == nil {
			filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
				if err != nil { return nil }
				if !info.IsDir() && strings.HasSuffix(strings.ToLower(path), ".iso") {
					found = append(found, map[string]string{
						"name": info.Name(),
						"path": path,
						"size_mb": fmt.Sprintf("%.1f MB", float64(info.Size())/1024/1024),
						"iso_type": detectISOType(info.Name()),
					})
				}
				// Limitar profundidade para não demorar
				if info.IsDir() && strings.Count(path, string(os.PathSeparator)) > 2 {
					return filepath.SkipDir
				}
				return nil
			})
		}
	}
	json.NewEncoder(w).Encode(found)
}

func handleNetInterfaces(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	type InterfaceInfo struct {
		Name string `json:"name"`
		IP   string `json:"ip"`
		MAC  string `json:"mac"`
	}
	ifaces, _ := net.Interfaces()
	res := []InterfaceInfo{}
	for _, i := range ifaces {
		addrs, _ := i.Addrs()
		for _, addr := range addrs {
			var ip net.IP
			switch v := addr.(type) {
			case *net.IPNet: ip = v.IP
			case *net.IPAddr: ip = v.IP
			}
			if ip != nil && ip.To4() != nil && !ip.IsLoopback() {
				res = append(res, InterfaceInfo{Name: i.Name, IP: ip.String(), MAC: i.HardwareAddr.String()})
			}
		}
	}
	json.NewEncoder(w).Encode(res)
}

func handleNetSelect(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	ip := r.URL.Query().Get("ip")
	if ip == "" {
		http.Error(w, "IP é obrigatório", 400)
		return
	}
	mu.Lock()
	state.SelectedIP = ip
	mu.Unlock()
	log.Printf("[NET] Interface de saída definida para %s", ip)
	
	// Reinicia serviços automaticamente se já estiverem rodando
	mu.Lock()
	if state.Running {
		mu.Unlock()
		log.Println("[NET] Reiniciando motores no novo IP...")
		handleStart(nil, nil) // Chamada interna segura pois handleStart agora limpa os antigos
	} else {
		mu.Unlock()
	}
	
	if w != nil { json.NewEncoder(w).Encode(map[string]bool{"success": true}) }
}

// ─────────────────────────────────────────────
// Lógica de Preparação de ISOs (Extração e Hooks)
// ─────────────────────────────────────────────

func handleISOPrepare(w http.ResponseWriter, r *http.Request) {
	name := r.URL.Query().Get("name")
	isoMu.Lock()
	var targetISO *ISOEntry
	for i := range isoList {
		if isoList[i].Name == name {
			targetISO = &isoList[i]
			break
		}
	}
	isoMu.Unlock()

	if targetISO == nil {
		http.Error(w, "ISO não encontrada", 404)
		return
	}

	go func() {
		mu.Lock()
		ip := state.SelectedIP
		mu.Unlock()
		if ip == "" { ip = "127.0.0.1" }

		targetISO.Status = "extracting"
		log.Printf("[ISO] Preparando ambiente para %s...", name)

		if err := prepareISO(targetISO); err != nil {
			log.Printf("[ERRO] Falha na extração de %s: %v", name, err)
			targetISO.Status = "error"
			return
		}

		if err := generateHooks(targetISO, ip); err != nil {
			log.Printf("[ERRO] Falha nos hooks de %s: %v", name, err)
			targetISO.Status = "error"
			return
		}

		targetISO.Status = "ready"
		log.Printf("[ISO] %s está PRONTA para boot iPXE", name)
	}()

	w.WriteHeader(http.StatusAccepted)
	json.NewEncoder(w).Encode(map[string]string{"status": "started"})
}

func prepareISO(iso *ISOEntry) error {
	targetDir := filepath.Join("./data/extracted", iso.Key)
	os.MkdirAll(targetDir, 0755)

	absIso, _ := filepath.Abs(iso.Path)
	absTarget, _ := filepath.Abs(targetDir)

	psCmd := fmt.Sprintf(`
		$ErrorActionPreference = 'Stop';
		log-message "Iniciando Mount-DiskImage para %s"
		Mount-DiskImage -ImagePath '%s' -StorageType ISO;
		$vi = Get-DiskImage -ImagePath '%s' | Get-Volume;
		if ($vi) {
			$d = $vi.DriveLetter + ':';
			log-message "ISO montada em $d. Iniciando copia seletiva..."
			$targets = @{
				'bootmgr' = 'bootmgr';
				'boot.sdi' = 'boot.sdi';
				'BCD' = 'BCD';
				'boot.wim' = 'boot.wim';
				'bootx64.efi' = 'bootx64.efi';
				'bootmgfw.efi' = 'bootmgfw.efi'
			}
			foreach ($t in $targets.Keys) {
				$f = Get-ChildItem -Path $d -Filter $targets[$t] -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1;
				if ($f) {
					$dest = Join-Path '%s' $t;
					Copy-Item $f.FullName $dest -Force;
				}
			}
			# Fallback para boot.wim se nao encontrar pelo nome exato
			if (-not (Test-Path (Join-Path '%s' 'boot.wim'))) {
				$maxWim = Get-ChildItem -Path $d -Filter *.wim -Recurse | Sort-Object Length -Descending | Select-Object -First 1;
				if ($maxWim) { Copy-Item $maxWim.FullName (Join-Path '%s' 'boot.wim') -Force }
			}
			Dismount-DiskImage -ImagePath '%s';
			# LIMPEZA DE ATRIBUTOS (Crucial para evitar 404 no Servidor HTTP)
			log-message "Limpando atributos de Hidden/System/ReadOnly em %s"
			Get-ChildItem -Path '%s' -Recurse | ForEach-Object {
				$_.Attributes = 'Archive'
			}
		} else {
			throw "Nao foi possivel localizar o Volume da ISO montada."
		}
		function log-message($m) { Write-Host "[PS] $m" }
	`, absIso, absIso, absIso, absTarget, absTarget, absTarget, absIso, absTarget, absTarget)

	cmd := exec.Command("powershell", "-Command", psCmd)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("PowerShell: %v | Output: %s", err, string(out))
	}
	return nil
}

func generateHooks(iso *ISOEntry, serverIP string) error {
	targetDir := filepath.Join("./data/extracted", iso.Key)
	
	// hook.cmd: O cérebro da montagem remota via HTTPDisk
	hookContent := fmt.Sprintf(`@echo off
color 0b
echo ====================================================
echo   4MCSERVER - Hook Engine V2.0
echo   ISO: %s ^| Servidor: %s
echo ====================================================
wpeinit
echo [1/3] Aguardando rede...
ping -n 5 %s >nul
echo [2/3] Instalando driver HTTPDisk...
sc create HttpDisk binpath= "X:\Windows\System32\drivers\httpdisk.sys" type= kernel start= demand 2>nul
sc start HttpDisk
echo [3/3] Montando ISO via HTTP...
X:\Windows\System32\httpdisk.exe /mount 0 http://%s:8080/iso/%s /size 0 Y:
if exist Y:\ (
    echo [SUCESSO] ISO montada em Y:\
    if exist Y:\SSTR\MInst\MInst.exe (
        echo [INFO] Detectado Sergei Strelec. Iniciando PECMD...
        pecmd.exe MAIN %%SystemRoot%%\System32\pecmd.ini
    ) else if exist Y:\setup.exe (
        echo [INFO] Detectado Instalador Windows.
        Y:\setup.exe
    ) else (
        echo [INFO] ISO Generica. Abrindo Explorer...
        start explorer.exe Y:\
    )
) else (
    echo [ERRO] Falha critica ao montar ISO remota!
    pause
    cmd.exe
)
`, iso.Name, serverIP, serverIP, serverIP, iso.Name)

	os.WriteFile(filepath.Join(targetDir, "hook.cmd"), []byte(hookContent), 0644)
	os.WriteFile(filepath.Join(targetDir, "startnet.cmd"), []byte("@echo off\nX:\\Windows\\System32\\hook.cmd\n"), 0644)
	os.WriteFile(filepath.Join(targetDir, "winpeshl.ini"), []byte("[LaunchApps]\nX:\\Windows\\System32\\hook.cmd\n"), 0644)
	
	if strings.Contains(strings.ToLower(iso.Name), "strelec") {
		pecmdContent := `EXEC =!CMD.EXE /C "X:\Windows\System32\hook.cmd"
IF EX Y:\SSTR\pecmd.ini,LOAD Y:\SSTR\pecmd.ini
`
		os.WriteFile(filepath.Join(targetDir, "pecmd.ini"), []byte(pecmdContent), 0644)
	}
	return nil
}

func handleMenu(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/plain")
	isoMu.Lock()
	defer isoMu.Unlock()

	var sb strings.Builder
	sb.WriteString("#!ipxe\n\n")
	sb.WriteString("set menu-timeout 8000\n")
	sb.WriteString("menu 4MCSERVER PXE Engine v2.0\n")
	sb.WriteString("item --gap --             --- BIBLIOTECA DE ISOS ---\n")

	for i, iso := range isoList {
		sb.WriteString(fmt.Sprintf("item iso_%d %s [%s]\n", i, iso.Name, iso.SizeMB))
	}
	
	sb.WriteString("item --gap --             --- UTILITARIOS ---\n")
	sb.WriteString("item shell                iPXE Shell\n")
	sb.WriteString("item reboot               Reiniciar\n\n")

	for i, iso := range isoList {
		sb.WriteString(fmt.Sprintf(":iso_%d\n", i))
		if iso.Status == "ready" {
			base := fmt.Sprintf("http://${next-server}:8080")
			sb.WriteString(fmt.Sprintf("kernel %s/boot/wimboot gui rawbcd\n", base))
			sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/bootmgr      bootmgr\n", base, iso.Key))
			sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/BCD          BCD\n", base, iso.Key))
			sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/boot.sdi      boot.sdi\n", base, iso.Key))
			
			if strings.Contains(strings.ToLower(iso.Name), "strelec") {
				sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/boot.wim   SSTR/system/SSTR10X64.WIM\n", base, iso.Key))
				sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/pecmd.ini  Windows/System32/pecmd.ini\n", base, iso.Key))
			} else {
				sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/boot.wim   sources/boot.wim\n", base, iso.Key))
			}
			
			sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/hook.cmd      Windows/System32/hook.cmd\n", base, iso.Key))
			sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/startnet.cmd  Windows/System32/startnet.cmd\n", base, iso.Key))
			sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/winpeshl.ini  Windows/System32/winpeshl.ini\n", base, iso.Key))
			sb.WriteString(fmt.Sprintf("initrd %s/boot/httpdisk.sys      Windows/System32/drivers/httpdisk.sys\n", base))
			sb.WriteString(fmt.Sprintf("initrd %s/boot/httpdisk.exe      Windows/System32/httpdisk.exe\n", base))
			sb.WriteString("boot\n\n")
		} else {
			sb.WriteString(fmt.Sprintf("sanboot http://${next-server}:8080/iso/%s\n\n", iso.Name))
		}
	}

	sb.WriteString(":shell\nshell\n\n")
	sb.WriteString(":reboot\nreboot\n")

	w.Write([]byte(sb.String()))
}

// ─────────────────────────────────────────────
// Auxiliares
// ─────────────────────────────────────────────

func detectISOType(name string) string {
	l := strings.ToLower(name)
	if strings.Contains(l, "strelec") || strings.Contains(l, "win") { return "WinPE" }
	if strings.Contains(l, "ubuntu") || strings.Contains(l, "linux") || strings.Contains(l, "debian") { return "Linux" }
	if strings.Contains(l, "clone") || strings.Contains(l, "parted") || strings.Contains(l, "kaspersky") { return "Utility" }
	return "Generic"
}

func addISO(path string) (ISOEntry, error) {
	info, err := os.Stat(path)
	if err != nil { return ISOEntry{}, err }
	name := filepath.Base(path)
	isoMu.Lock()
	defer isoMu.Unlock()
	entry := ISOEntry{
		Name:   name,
		Size:   info.Size(),
		SizeMB: fmt.Sprintf("%.1f MB", float64(info.Size())/1024/1024),
		Type:   detectISOType(name),
		Path:   path,
		Ready:  true,
		Key:    strings.ToLower(regexp.MustCompile(`[^a-zA-Z0-9]`).ReplaceAllString(strings.Replace(name, ".iso", "", -1), "")),
		Status: "none",
	}
	// Auto-detectar se já está pronta (evita re-extração desnecessária)
	if _, err := os.Stat(filepath.Join("./data/extracted", entry.Key, "boot.wim")); err == nil {
		entry.Status = "ready"
	}
	isoList = append(isoList, entry)
	return entry, nil
}

func scanISOFolder() int {
	files, _ := filepath.Glob(filepath.Join(isoFolder, "*.[iI][sS][oO]"))
	count := 0
	for _, f := range files {
		if _, err := addISO(f); err == nil { count++ }
	}
	return count
}

func watchISOs() {
	for {
		time.Sleep(15 * time.Second)
		scanISOFolder()
	}
}
