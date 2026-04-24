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
// Tipos
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
// Estado Global
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
// Captura de Logs
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
	if len(l.logs) > 100 {
		l.logs = l.logs[1:]
	}
	l.mu.Unlock()
	return len(p), nil
}

var logCatcher = &LogCapture{}

// ─────────────────────────────────────────────
// Main
// ─────────────────────────────────────────────

func main() {
	log.SetOutput(logCatcher)
	log.Println("[INFO] 4MCSERVER v2.0 (High Performance PXE) iniciando...")
	os.MkdirAll(isoFolder, 0755)
	os.MkdirAll("./data/extracted", 0755)

	// Scan imediato da pasta iso/ ao iniciar
	count := scanISOFolder()
	if count > 0 {
		log.Printf("[ISO] %d ISO(s) carregada(s) da pasta iso/ na inicialização", count)
	}

	go watchISOs()

	mux := http.NewServeMux()

	// API endpoints — registrados ANTES do FileServer
	mux.HandleFunc("/api/status",       handleStatus)
	mux.HandleFunc("/api/logs",         handleLogs)
	mux.HandleFunc("/api/start",        handleStart)
	mux.HandleFunc("/api/stop",         handleStop)
	mux.HandleFunc("/api/isos",         handleISOs)
	mux.HandleFunc("/api/isos/scan",    handleISOScan)
	mux.HandleFunc("/api/isos/add",     handleISOAdd)
	mux.HandleFunc("/api/isos/remove",  handleISORemove)
	mux.HandleFunc("/api/isos/browse",  handleISOBrowse)
	mux.HandleFunc("/api/network/interfaces", handleNetInterfaces)
	mux.HandleFunc("/api/network/select",     handleNetSelect)
	mux.HandleFunc("/api/isos/prepare",    handleISOPrepare)
	mux.HandleFunc("/menu.ipxe",              handleMenu)

	// Virtual mapping for extracted files
	mux.Handle("/virtual/", http.StripPrefix("/virtual/", http.FileServer(http.Dir("./data/extracted"))))

	// Static — catchall e pastas vitais
	mux.Handle("/iso/", http.StripPrefix("/iso/", http.FileServer(http.Dir("./iso"))))
	mux.Handle("/boot/", http.StripPrefix("/boot/", http.FileServer(http.Dir("./boot"))))
	mux.Handle("/", http.FileServer(http.Dir("./static")))

	log.Println("[INFO] Painel 4MCSERVER disponível em http://localhost:8080")
	
	// Logging Middleware
	loggedMux := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		log.Printf("[HTTP] %s %s", r.Method, r.URL.Path)
		mux.ServeHTTP(w, r)
	})

	go func() {
		if err := http.ListenAndServe(":8080", loggedMux); err != nil {
			log.Fatalf("[ERRO] Servidor web: %v", err)
		}
	}()

	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)
	<-sigs
	log.Println("[INFO] Encerrando...")
	if dhcpServer != nil {
		dhcpServer.Stop()
	}
}

// ─────────────────────────────────────────────
// Handlers de API
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
	w.Header().Set("Content-Type", "application/json")
	mu.Lock()
	defer mu.Unlock()
	if !state.Running {
		// Se não houver IP selecionado, tenta pegar o primeiro razoável
		listenIP := state.SelectedIP
		if listenIP == "" { listenIP = "0.0.0.0" }

		srv := dhcp.NewServer(listenIP)
		if err := srv.Listen(); err != nil {
			log.Printf("[ERRO] DHCP em %s: %v", listenIP, err)
			http.Error(w, err.Error(), 500)
			return
		}
		dhcpServer = srv

		// Iniciar TFTP também
		bootDir := "./boot"
		os.MkdirAll(bootDir, 0755)
		tftpServer = tftp.NewServer(bootDir)
		if err := tftpServer.Listen(); err != nil {
			log.Printf("[ERRO] TFTP: %v", err)
		}

		state.Running = true
		log.Printf("[INFO] Motor DHCP iniciado — Interface: %s porta 67", listenIP)
	}
	json.NewEncoder(w).Encode(map[string]string{"status": "started"})
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
				res = append(res, InterfaceInfo{
					Name: i.Name,
					IP:   ip.String(),
					MAC:  i.HardwareAddr.String(),
				})
			}
		}
	}
	json.NewEncoder(w).Encode(res)
}

func handleNetSelect(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	ip := r.URL.Query().Get("ip")
	if ip == "" {
		http.Error(w, "IP requerido", 400)
		return
	}
	mu.Lock()
	state.SelectedIP = ip
	mu.Unlock()
	log.Printf("[NET] Interface selecionada: %s", ip)
	json.NewEncoder(w).Encode(map[string]bool{"success": true})
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
		log.Println("[INFO] Servidores parados")
	}
	json.NewEncoder(w).Encode(map[string]string{"status": "stopped"})
}

// GET /api/isos — lista as ISOs registradas
func handleISOs(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	isoMu.Lock()
	defer isoMu.Unlock()
	json.NewEncoder(w).Encode(isoList)
}

// POST /api/isos/scan — escaneia a pasta iso/ e registra o que encontrar
func handleISOScan(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	count := scanISOFolder()
	log.Printf("[ISO] Scan concluído: %d ISO(s) encontrada(s)", count)
	json.NewEncoder(w).Encode(map[string]interface{}{"found": count})
}

// POST /api/isos/add  body: {"path":"C:\\Users\\...\\minha.iso"}
func handleISOAdd(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	if r.Method != http.MethodPost {
		http.Error(w, "POST only", 405)
		return
	}
	var body struct {
		Path string `json:"path"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Path == "" {
		http.Error(w, "body inválido: {\"path\":\"...\"}", 400)
		return
	}
	entry, err := addISO(body.Path)
	if err != nil {
		http.Error(w, err.Error(), 400)
		return
	}
	log.Printf("[ISO] Adicionada: %s (%s)", entry.Name, entry.SizeMB)
	json.NewEncoder(w).Encode(entry)
}

// DELETE /api/isos/remove?name=arquivo.iso
func handleISORemove(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	name := r.URL.Query().Get("name")
	if name == "" {
		http.Error(w, "?name= requerido", 400)
		return
	}
	isoMu.Lock()
	defer isoMu.Unlock()
	newList := []ISOEntry{}
	removed := false
	for _, iso := range isoList {
		if iso.Name == name {
			removed = true
			log.Printf("[ISO] Removida: %s", name)
		} else {
			newList = append(newList, iso)
		}
	}
	isoList = newList
	json.NewEncoder(w).Encode(map[string]bool{"removed": removed})
}

// POST /api/isos/prepare?name=arquivo.iso
func handleISOPrepare(w http.ResponseWriter, r *http.Request) {
	name := r.URL.Query().Get("name")
	if name == "" {
		http.Error(w, "?name= requerido", 400)
		return
	}

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
		serverIP := state.SelectedIP
		mu.Unlock()
		if serverIP == "" { serverIP = "127.0.0.1" }

		targetISO.Status = "extracting"
		log.Printf("[ISO] Iniciando extração: %s", name)
		
		err := prepareISO(targetISO)
		if err != nil {
			log.Printf("[ERRO] Falha na extração de %s: %v", name, err)
			targetISO.Status = "error"
			return
		}

		err = generateHooks(targetISO, serverIP)
		if err != nil {
			log.Printf("[ERRO] Falha ao gerar hooks para %s: %v", name, err)
			targetISO.Status = "error"
			return
		}

		targetISO.Status = "ready"
		log.Printf("[ISO] Pronta para boot: %s", name)
	}()

	w.WriteHeader(http.StatusAccepted)
	json.NewEncoder(w).Encode(map[string]string{"status": "started"})
}

func prepareISO(iso *ISOEntry) error {
	targetDir := filepath.Join("./data/extracted", iso.Key)
	os.MkdirAll(targetDir, 0755)

	absIsoPath, _ := filepath.Abs(iso.Path)
	absTargetDir, _ := filepath.Abs(targetDir)

	psCmd := fmt.Sprintf(`
		$ErrorActionPreference = 'Stop';
		$iso = '%s';
		$target = '%s';
		Mount-DiskImage -ImagePath $iso;
		$vi = Get-DiskImage -ImagePath $iso | Get-Volume;
		if ($vi) {
			$d = $vi.DriveLetter + ':';
			$targets = @{
				'bootmgr' = 'bootmgr';
				'boot.sdi' = 'boot.sdi';
				'BCD' = 'BCD';
				'boot.wim' = 'boot.wim';
				'bootx64.efi' = 'bootx64.efi';
				'bootmgfw.efi' = 'bootmgfw.efi';
			}
			foreach ($t in $targets.Keys) {
				$f = Get-ChildItem -Path $d -Filter $targets[$t] -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1;
				if ($f) {
					$dest = Join-Path $target $t;
					cp $f.FullName $dest -Force;
				}
			}
			if (-not (Test-Path (Join-Path $target 'boot.wim'))) {
				$maxWim = Get-ChildItem -Path $d -Filter *.wim -Recurse -ErrorAction SilentlyContinue | Sort-Object Length -Descending | Select-Object -First 1;
				if ($maxWim) { cp $maxWim.FullName (Join-Path $target 'boot.wim') -Force; }
			}
			Dismount-DiskImage -ImagePath $iso;
		} else {
			throw "Falha ao obter volume da ISO montada.";
		}
	`, absIsoPath, absTargetDir)

	cmd := exec.Command("powershell", "-Command", psCmd)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("PowerShell error: %v, Output: %s", err, string(out))
	}
	return nil
}

func generateHooks(iso *ISOEntry, serverIP string) error {
	targetDir := filepath.Join("./data/extracted", iso.Key)
	
	// hook.cmd
	hookContent := fmt.Sprintf(`@echo off
color 0b
echo ====================================================
echo   4MCSERVER - Hook Engine Executing
echo   ISO: %s | Servidor: %s
echo ====================================================
wpeinit
ping -n 5 %s >nul
sc create HttpDisk binpath= "X:\Windows\System32\drivers\httpdisk.sys" type= kernel start= demand 2>nul
sc start HttpDisk
X:\Windows\System32\httpdisk.exe /mount 0 http://%s:8080/iso/%s /size 0 Y:
if exist Y:\ (
    echo [SUCESSO] ISO montada em Y:
    if exist Y:\SSTR\MInst\MInst.exe (
        pecmd.exe MAIN %%SystemRoot%%\System32\pecmd.ini
    ) else if exist Y:\setup.exe (
        Y:\setup.exe
    ) else (
        start explorer.exe Y:\
    )
) else (
    echo [ERRO] Falha ao montar Y:
    pause
    cmd.exe
)
`, iso.Name, serverIP, serverIP, serverIP, iso.Name)

	os.WriteFile(filepath.Join(targetDir, "hook.cmd"), []byte(hookContent), 0644)
	os.WriteFile(filepath.Join(targetDir, "startnet.cmd"), []byte("@echo off\nX:\\Windows\\System32\\hook.cmd\n"), 0644)
	os.WriteFile(filepath.Join(targetDir, "winpeshl.ini"), []byte("[LaunchApps]\nX:\\Windows\\System32\\hook.cmd\n"), 0644)
	
	if strings.Contains(strings.ToLower(iso.Name), "strelec") {
		pecmdContent := `# Strelec Seizure
EXEC =!CMD.EXE /C "X:\Windows\System32\hook.cmd"
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
	sb.WriteString("set menu-timeout 5000\n")
	sb.WriteString("menu GEMINIFLASH - Modern PXE Boot\n")
	sb.WriteString("item --gap --             --- ISO LIBRARY ---\n")

	for i, iso := range isoList {
		sb.WriteString(fmt.Sprintf("item iso_%d %s (%s)\n", i, iso.Name, iso.SizeMB))
	}
	sb.WriteString("item --gap --             --- SYSTEM ---\n")
	for i, iso := range isoList {
		sb.WriteString(fmt.Sprintf(":iso_%d\n", i))
		if iso.Status == "ready" {
			// Boot avançado via HTTPDisk Hooking
			base_url := fmt.Sprintf("http://${next-server}:8080")
			sb.WriteString(fmt.Sprintf("kernel %s/boot/wimboot gui rawbcd\n", base_url))
			sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/bootmgr      bootmgr\n", base_url, iso.Key))
			sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/BCD          boot/bcd\n", base_url, iso.Key))
			sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/BCD          EFI/Microsoft/Boot/BCD\n", base_url, iso.Key))
			sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/boot.sdi      boot/boot.sdi\n", base_url, iso.Key))
			
			// Detecta se eh Strelec pelo nome ou status (simplificado)
			if strings.Contains(strings.ToLower(iso.Name), "strelec") {
				sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/boot.wim   SSTR/system/SSTR10X64.WIM\n", base_url, iso.Key))
				sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/pecmd.ini  Windows/System32/pecmd.ini\n", base_url, iso.Key))
			} else {
				sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/boot.wim   sources/boot.wim\n", base_url, iso.Key))
			}
			
			sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/hook.cmd      Windows/System32/hook.cmd\n", base_url, iso.Key))
			sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/startnet.cmd  Windows/System32/startnet.cmd\n", base_url, iso.Key))
			sb.WriteString(fmt.Sprintf("initrd %s/virtual/%s/winpeshl.ini  Windows/System32/winpeshl.ini\n", base_url, iso.Key))
			sb.WriteString(fmt.Sprintf("initrd %s/boot/httpdisk.sys      Windows/System32/drivers/httpdisk.sys\n", base_url))
			sb.WriteString(fmt.Sprintf("initrd %s/boot/httpdisk.exe      Windows/System32/httpdisk.exe\n", base_url))
			sb.WriteString("boot\n\n")
		} else {
			// Lógica estilo iVentoy: Boot direto via HTTP (sanboot)
			sb.WriteString(fmt.Sprintf("sanboot http://${next-server}:8080/iso/%s\n\n", iso.Name))
		}
	}
	
	// Adiciona a rota hardcoded do Strelec HTTPDisk
	sb.WriteString(":strelec_httpdisk\n")
	sb.WriteString("kernel http://${next-server}:8080/boot/wimboot gui rawbcd\n")
	sb.WriteString("initrd http://${next-server}:8080/iso/strelec_extracted/bootmgr bootmgr\n")
	sb.WriteString("initrd http://${next-server}:8080/iso/strelec_extracted/boot/bcd boot/bcd\n")
	sb.WriteString("initrd http://${next-server}:8080/iso/strelec_extracted/boot/boot.sdi boot/boot.sdi\n")
	sb.WriteString("initrd http://${next-server}:8080/iso/strelec_extracted/SSTR/system/SSTR10X64.WIM SSTR/system/SSTR10X64.WIM\n")
	sb.WriteString("initrd http://${next-server}:8080/boot/httpdisk.sys Windows/System32/drivers/httpdisk.sys\n")
	sb.WriteString("initrd http://${next-server}:8080/boot/httpdisk.exe Windows/System32/httpdisk.exe\n")
	sb.WriteString("initrd http://${next-server}:8080/boot/startnet.cmd Windows/System32/startnet.cmd\n")
	sb.WriteString("boot\n\n")

	sb.WriteString(":shell\nshell\n\n")
	sb.WriteString(":exit\nreboot\n")

	w.Write([]byte(sb.String()))
}

// ─────────────────────────────────────────────
// Lógica de ISO
// ─────────────────────────────────────────────

func detectISOType(name string) string {
	lower := strings.ToLower(name)
	switch {
	case strings.Contains(lower, "strelec") || strings.Contains(lower, "winpe") || strings.Contains(lower, "win"):
		return "WinPE"
	case strings.Contains(lower, "ubuntu") || strings.Contains(lower, "debian") || strings.Contains(lower, "fedora") || strings.Contains(lower, "arch"):
		return "Linux"
	case strings.Contains(lower, "clonezilla") || strings.Contains(lower, "gparted"):
		return "Utility"
	default:
		return "Generic"
	}
}

func addISO(path string) (ISOEntry, error) {
	info, err := os.Stat(path)
	if err != nil {
		return ISOEntry{}, fmt.Errorf("arquivo não encontrado: %s", path)
	}
	if !strings.HasSuffix(strings.ToLower(path), ".iso") {
		return ISOEntry{}, fmt.Errorf("arquivo não é .iso")
	}
	name := filepath.Base(path)

	isoMu.Lock()
	defer isoMu.Unlock()
	for _, iso := range isoList {
		if iso.Name == name {
			return iso, nil // já existe
		}
	}
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
	// Verifica se já está preparada
	if _, err := os.Stat(filepath.Join("./data/extracted", entry.Key, "boot.wim")); err == nil {
		entry.Status = "ready"
	}
	isoList = append(isoList, entry)
	return entry, nil
}

func scanISOFolder() int {
	// Procura por .iso e .ISO (alguns Windows sao chatos com isso)
	files, _ := filepath.Glob(filepath.Join(isoFolder, "*.[iI][sS][oO]"))
	count := 0
	for _, f := range files {
		if _, err := addISO(f); err == nil {
			count++
		}
	}
	return count
}

// GET /api/isos/browse?drives=true — varre discos por ISOs
func handleISOBrowse(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	type FoundISO struct {
		Name   string `json:"name"`
		Path   string `json:"path"`
		SizeMB string `json:"size_mb"`
		Type   string `json:"iso_type"`
	}

	// Começa pela pasta iso/ local
	found := []FoundISO{}
	searchDirs := []string{isoFolder}

	// Adiciona raízes de todos os discos disponíveis
	for _, letter := range "CDEFGHIJKLMNOPQRSTUVWXYZ" {
		root := string(letter) + `:\`
		if info, err := os.Stat(root); err == nil && info.IsDir() {
			// Busca em subpastas comuns para não demorar
			for _, sub := range []string{"", "iso", "ISOs", "ISO", "images", "Images"} {
				dir := filepath.Join(root, sub)
				searchDirs = append(searchDirs, dir)
			}
		}
	}

	log.Printf("[BROWSE] Escaneando %d diretórios...", len(searchDirs))
	for _, dir := range searchDirs {
		files, err := os.ReadDir(dir)
		if err != nil {
			continue
		}
		for _, f := range files {
			if f.IsDir() || !strings.HasSuffix(strings.ToLower(f.Name()), ".iso") {
				continue
			}
			path := filepath.Join(dir, f.Name())
			info, err := f.Info()
			if err != nil {
				continue
			}
			found = append(found, FoundISO{
				Name:   f.Name(),
				Path:   path,
				SizeMB: fmt.Sprintf("%.1f GB", float64(info.Size())/1024/1024/1024),
				Type:   detectISOType(f.Name()),
			})
		}
	}

	log.Printf("[BROWSE] %d ISO(s) encontrada(s) no scan de discos", len(found))
	json.NewEncoder(w).Encode(found)
}

// ─────────────────────────────────────────────
// Watcher automático (estilo iVentoy)
// ─────────────────────────────────────────────

func watchISOs() {
	for {
		time.Sleep(10 * time.Second)
		scanISOFolder()
	}
}
