package dhcp

import (
	"net"
)

// DHCPPacket structure (Simplified)
type DHCPPacket []byte

func NewPacket(op byte, xid []byte, chaddr []byte) DHCPPacket {
	p := make(DHCPPacket, 300) // Aumentado para 300 bytes para satisfazer placas chatas
	p[0] = op                  // Boot Reply (2)
	p[1] = 1                   // Htype (Ethernet)
	p[2] = 6                   // Hlen
	p[3] = 0                   // Hops
	copy(p[4:8], xid)          // Transaction ID
	p[10] = 128                // 0x80 Flags: Broadcast (Crucial para VirtualBox)
	copy(p[28:34], chaddr)     // Client MAC
	
	// Magic Cookie
	copy(p[236:240], []byte{99, 130, 83, 99})
	return p
}

func (p DHCPPacket) AddOption(code byte, value []byte) DHCPPacket {
	p = append(p, code)
	p = append(p, byte(len(value)))
	p = append(p, value...)
	return p
}

func (p DHCPPacket) End() DHCPPacket {
	return append(p, 255)
}

func (p DHCPPacket) SetYIAddr(ip net.IP) {
	copy(p[16:20], ip.To4())
}

func (p DHCPPacket) SetSIAddr(ip net.IP) {
	copy(p[20:24], ip.To4())
}

func (p DHCPPacket) SetFile(file string) {
	b := make([]byte, 128)
	copy(b, []byte(file))
	copy(p[108:236], b)
}
