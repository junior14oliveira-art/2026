package tftp

import (
	"log"
	"net"
	"os"
	"path/filepath"
	"time"
)

type Server struct {
	IP       string
	BootPath string
	Running  bool
	conn     *net.UDPConn
}

func NewServer(ip string, path string) *Server {
	return &Server{IP: ip, BootPath: path}
}

func (s *Server) Listen() error {
	addr, err := net.ResolveUDPAddr("udp4", s.IP+":69")
	if err != nil {
		return err
	}
	conn, err := net.ListenUDP("udp4", addr)
	if err != nil {
		return err
	}
	s.conn = conn
	s.Running = true
	log.Printf("[TFTP] Motor GEMINIFLASH ativo na porta 69 (Path: %s)", s.BootPath)
	go s.serve()
	return nil
}

func (s *Server) serve() {
	buf := make([]byte, 1024)
	for s.Running {
		n, addr, err := s.conn.ReadFromUDP(buf)
		if err != nil { continue }
		
		// Lógica básica de leitura TFTP (Opcode 1 = Read Request)
		if n > 2 && buf[1] == 1 {
			filename := ""
			for i := 2; i < n; i++ {
				if buf[i] == 0 { break }
				filename += string(buf[i])
			}
			log.Printf("[TFTP] Request: %s de %v", filename, addr)
			go s.sendFile(filename, addr)
		}
	}
}

func (s *Server) sendFile(name string, addr *net.UDPAddr) {
	path := filepath.Join(s.BootPath, name)
	data, err := os.ReadFile(path)
	if err != nil {
		log.Printf("[TFTP] Erro arquivo %s: %v", name, err)
		return
	}

	blockSize := 512
	localAddr, _ := net.ResolveUDPAddr("udp4", s.IP+":0") // Porta efemera no IP certo
	conn, _ := net.DialUDP("udp4", localAddr, addr)
	defer conn.Close()

	ackBuf := make([]byte, 16)
	for i := 0; i < len(data); i += blockSize {
		end := i + blockSize
		if end > len(data) { end = len(data) }
		
		blockNum := uint16(i/blockSize + 1)
		packet := []byte{0, 3, byte(blockNum >> 8), byte(blockNum & 0xFF)}
		packet = append(packet, data[i:end]...)
		
		// Envia e espera ACK (Opcode 4)
		_, _ = conn.Write(packet)
		
		// Timeout de 1s para o ACK
		conn.SetReadDeadline(time.Now().Add(1 * time.Second))
		n, _, err := conn.ReadFromUDP(ackBuf)
		if err != nil || n < 4 || ackBuf[1] != 4 {
			log.Printf("[TFTP] Falha no ACK para o bloco %d", blockNum)
			return
		}
	}
	log.Printf("[TFTP] Transferência de %s concluída para %v", name, addr)
}

func (s *Server) Stop() {
	s.Running = false
	if s.conn != nil { s.conn.Close() }
}
