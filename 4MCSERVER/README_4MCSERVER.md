# 4MCSERVER v2.0 - Documentação Técnica

## 🚀 Visão Geral
O **4MCSERVER** é um servidor PXE de alta performance escrito em Go. Ele foi projetado para substituir soluções instáveis em Python, oferecendo um motor de boot robusto capaz de carregar ISOs gigantes (como Sergei Strelec) via rede usando a tecnologia **HTTPDisk**.

## 🛠 Arquitetura
- **Go Engine**: Responsável pelo DHCP, TFTP e Servidor HTTP.
- **HTTPDisk Hooking**: Técnica que extrai apenas o bootloader da ISO para a RAM e monta o restante via HTTP.
- **iPXE Dynamic Menu**: Gera menus de boot baseados na biblioteca de ISOs local.

## 📋 Como usar
1. Execute o `START_4MCSERVER.bat` como Administrador.
2. Coloque suas ISOs na pasta `iso/`.
3. Acesse o painel em `http://localhost:8080`.
4. Para ISOs de Windows/WinPE, clique em **"Preparar Hook"** para extrair os componentes de boot necessários.

## 🔌 Solução de Problemas (Rede Real vs VirtualBox)
Se o servidor funciona no VirtualBox mas não na rede física, verifique:
- **Firewall**: Garanta que as portas 67, 69 e 8080 estão abertas (o script tenta configurar isso automaticamente).
- **Interface**: Selecione o IP correto da sua placa de rede no menu **Network**.
- **ProxyDHCP**: Se houver outro roteador na rede, o 4MCSERVER tentará usar o modo ProxyDHCP para evitar conflitos.
- **Switch STP**: Se a placa de rede demora para dar link, ative o *PortFast* no seu switch.

---
Desenvolvido por Antigravity AI para junior14oliveira-art.
