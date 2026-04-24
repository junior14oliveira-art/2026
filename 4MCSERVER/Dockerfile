# Stage 1: Build
FROM golang:1.22-alpine AS builder

WORKDIR /app

# Copia arquivos do modulo
COPY go.mod ./
# RUN go mod download (Ativar se houver dependencias externas)

# Copia o codigo fonte
COPY . .

# Compila o binario estatico
RUN CGO_ENABLED=0 GOOS=linux go build -o geminiflash ./cmd/gemini/main.go

# Stage 2: Runtime
FROM alpine:latest

WORKDIR /root/

# Copia o binario e arquivos estaticos do builder
COPY --from=builder /app/geminiflash .
COPY --from=builder /app/static ./static

# Portas PXE (DHCP: 67, TFTP: 69, HTTP: 80, ProxyDHCP: 4011)
EXPOSE 67/udp 69/udp 80/tcp 4011/udp 8080/tcp

# Comando para iniciar
CMD ["./geminiflash"]
