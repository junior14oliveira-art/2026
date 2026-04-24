package dhcp

import (
	"fmt"
	"log"
	"net"
	"strings"
	"sync"
	"time"
)

// Server representa o servidor DHCP do GEMINIFLASH
type Server struct {
	IP        string
	Port      int
	Running   bool
	conn      *net.UDPConn
	macHits   map[string]int
	lastHit   map[string]time.Time
	macHitsMu sync.Mutex
}

// NewServer cria uma nova instancia do servidor
func NewServer(ip string) *Server {
	return &Server{
		IP:      ip,
		Port:    67,
		macHits: make(map[string]int),
		lastHit: make(map[string]time.Time),
	}
}

// Listen inicia a escuta de pacotes broadcast
func (s *Server) Listen() error {
	addr, err := net.ResolveUDPAddr("udp4", ":67")
	if err != nil {
		return err
	}

	conn, err := net.ListenUDP("udp4", addr)
	if err != nil {
		return err
	}
	s.conn = conn
	s.Running = true

	log.Printf("[DHCP] Servidor GEMINIFLASH ativo em %s:67", s.IP)

	go s.serve()
	return nil
}

func (s *Server) serve() {
	buf := make([]byte, 1024)
	
	// Pool de IPs simples (192.168.1.100-200)
	nextIP := byte(100)
	
	for s.Running {
		n, addr, err := s.conn.ReadFromUDP(buf)
		if err != nil {
			if s.Running {
				log.Printf("[DHCP] Erro na leitura: %v", err)
			}
			continue
		}

		if n < 240 { continue } // Pacote inválido
		
		// Copia o buffer para a goroutine
		packetData := make([]byte, n)
		copy(packetData, buf[:n])
		
		go s.handlePacket(packetData, n, addr, &nextIP)
	}
}

func (s *Server) handlePacket(buf []byte, n int, addr *net.UDPAddr, nextIP *byte) {

		op := buf[0]
		xid := buf[4:8]
		chaddr := buf[28:34]

		// Só respondemos a solicitações de BOOT (op 1)
		if op != 1 { return }

		// Descobrir OPÇÕES do Cliente
		var msgType byte = 1
		var isIPXE bool
		var arch uint16 = 0 // 0=BIOS, 7/9=UEFI
		var requestedIP net.IP
		
		// Parsing de opções (campo 240 em diante)
		for i := 240; i < n-2; {
			opt := buf[i]
			if opt == 255 { break }
			if opt == 0 { i++; continue }
			l := int(buf[i+1])
			if i+2+l > n { break }
			val := buf[i+2 : i+2+l]
			
			if opt == 53 { msgType = val[0] } // Message Type
			if opt == 77 && strings.Contains(string(val), "iPXE") { isIPXE = true } // User Class
			if opt == 93 && len(val) >= 2 { arch = uint16(val[0])<<8 | uint16(val[1]) } // Client Arch
			if opt == 50 && len(val) == 4 { requestedIP = net.IP(val) } // Requested IP
			
			i += 2 + l
		}

		macStr := fmt.Sprintf("%02x:%02x:%02x:%02x:%02x:%02x", 
			chaddr[0], chaddr[1], chaddr[2], chaddr[3], chaddr[4], chaddr[5])
		
		log.Printf("[DHCP] %s de %s (iPXE: %v, Arch: %d)", 
			map[byte]string{1:"DISCOVER", 3:"REQUEST"}[msgType], macStr, isIPXE, arch)

		// Craft da resposta
		respType := byte(2) // Offer
		if msgType == 3 { respType = 5 } // Ack
		
		res := NewPacket(2, xid, chaddr)
		
		// Determina o IP do servidor e garante IPv4 4-bytes base
		serverIP := net.ParseIP(s.IP)
		if s.IP == "0.0.0.0" || serverIP == nil { serverIP = s.getLocalIP() }
		serverIPv4 := serverIP.To4()
		if serverIPv4 == nil { serverIPv4 = net.IPv4(192, 168, 0, 1).To4() }
		
		// Gera IP para o cliente garantindo que usamos os octetos corretos
		clientIP := net.IPv4(serverIPv4[0], serverIPv4[1], serverIPv4[2], *nextIP)
		if requestedIP != nil && requestedIP.To4() != nil {
			clientIP = requestedIP.To4()
		}
		(*nextIP)++
		if *nextIP > 200 { *nextIP = 100 }
		
		// Define IPs no pacote
		res.SetYIAddr(clientIP)  // IP oferecido ao cliente
		res.SetSIAddr(serverIP)  // IP do servidor TFTP
		
		// ─────────────────────────────────────────────
		// Heurística Anti-Looping (Chainload Loop Breaker)
		// ─────────────────────────────────────────────
		// VirtualBox vem com iPXE nativo MAS sem suporte HTTP.
		// Precisamos forçar o VBox a carregar NOSSO undionly.kpxe (q tem HTTP).
		// Se respondermos sempre a URL HTTP, o VBox trava.
		// Se respondermos sempre kpxe, entra em loop infinito.
		// Solução: O primeiro request da placa ganha o arquivo binário.
		// O segundo request (já feito pelo nosso kpxe) ganha o Menu HTTP.
		
		bootFile := "ipxe.efi"
		if arch == 0 { bootFile = "undionly.kpxe" }

		s.macHitsMu.Lock()
		hits := s.macHits[macStr]
		
		// Reseta o contador se passou muito tempo (ex: 2 min sem uso)
		if time.Since(s.lastHit[macStr]) > 2 * time.Minute {
			hits = 0
		}
		
		bootPath := bootFile
		if hits > 0 {
			// Segundo boot (já deve ser nosso iPXE de alta performance com HTTP)
			bootPath = fmt.Sprintf("http://%s:8080/menu.ipxe", serverIP.String())
			res.SetFile(bootPath)
			log.Printf("[DHCP] Chainload Nível 2! Enviando Menu HTTP para %s", macStr)
		} else {
			// Primeiro boot (Força carregar nosso motor boot)
			res.SetFile(bootPath)
			log.Printf("[DHCP] Chainload Nível 1! Enviando motor %s para %s", bootFile, macStr)
		}
		
		// Registra o hit só pra Requests (que confirmam o recebimento) ou Discover repetido
		if msgType == 3 {
			s.macHits[macStr] = hits + 1
		}
		s.lastHit[macStr] = time.Now()
		s.macHitsMu.Unlock()

		// Opções DHCP em Ordem de Compatibilidade
		res = res.AddOption(53, []byte{respType})           // 1. Message Type
		res = res.AddOption(54, serverIP.To4())             // 2. Server ID
		res = res.AddOption(51, []byte{0, 1, 81, 128})      // 3. Lease Time (24h)
		res = res.AddOption(1,  []byte{255, 255, 255, 0})   // 4. Subnet Mask
		res = res.AddOption(3,  serverIP.To4())             // 5. Router (Gateway)
		res = res.AddOption(6,  serverIP.To4())             // 6. DNS Server
		res = res.AddOption(15, []byte("pxe.local"))        // 7. Domain Name
		
		if !isIPXE && bootFile != "menu.ipxe" {
			// Opções PXE para boot inicial (somente se não estiver enviando menu já)
			res = res.AddOption(60, []byte("PXEClient"))       
			res = res.AddOption(66, []byte(serverIP.String()))  // TFTP Server
			res = res.AddOption(67, []byte(bootPath))           // Bootfile
			res = res.AddOption(43, []byte{6, 1, 8, 10, 4, 0, 'P', 'X', 'E', 255}) // PXE Magic
			// Adiciona opção 97 (UUID) se existir para contornar problemas Dell
			// res = res.AddOption(97, ...) 
		} else {
			res = res.AddOption(67, []byte(bootPath))
		}
		
		res = res.End()

		// Descobre o Broadcast real da placa selecionada
		bcast := net.IPv4bcast
		addrs, _ := net.InterfaceAddrs()
		for _, a := range addrs {
			if ipnet, ok := a.(*net.IPNet); ok {
				if ipnet.IP.Equal(serverIP) {
					// Calcula o IP de broadcast (IP | ^MASK)
					mask := ipnet.Mask
					ip := ipnet.IP.To4()
					if ip != nil && mask != nil {
						bcast = net.IPv4(ip[0]|^mask[0], ip[1]|^mask[1], ip[2]|^mask[2], ip[3]|^mask[3])
					}
					break
				}
			}
		}

		// Envia Resposta p/ Broadcast Específico e Geral (Aumenta compatibilidade em Switch Físico)
		s.conn.WriteToUDP(res, &net.UDPAddr{IP: bcast, Port: 68})
		s.conn.WriteToUDP(res, &net.UDPAddr{IP: net.IPv4bcast, Port: 68})
		s.conn.WriteToUDP(res, &net.UDPAddr{IP: clientIP, Port: 68}) // Unicast direto se a rede permitir
		
		log.Printf("[DHCP] %s enviado para %v (Concurrency OK)", map[byte]string{2:"OFFER", 5:"ACK"}[respType], clientIP)
}

func (s *Server) getLocalIP() net.IP {
	addrs, _ := net.InterfaceAddrs()
	for _, a := range addrs {
		if ipnet, ok := a.(*net.IPNet); ok && !ipnet.IP.IsLoopback() {
			if ipnet.IP.To4() != nil {
				return ipnet.IP
			}
		}
	}
	return net.IPv4(127, 0, 0, 1)
}

// Stop desliga o servidor
func (s *Server) Stop() {
	s.Running = false
	if s.conn != nil {
		s.conn.Close()
	}
}
