# PXEGEMINI - Strelec Boot Analysis & Solution

## Problema
MInst.exe não abre no WinPE quando bootado via iPXE wimboot.
Erro: `Windows cannot find '\SSTR\MInst\MInst.exe'`

## Análise iVentoy vs Nosso Sistema

### iVentoy (funciona)
- Usa **httpdisk.sys** para montar a ISO inteira como disco Y:
- Todos os 7,400+ arquivos do SSTR ficam acessíveis
- MInst abre normalmente

### Nosso wimboot (não funciona)
- Carrega apenas boot.wim em RAM (X:)
- SSTR/ não está no boot.wim
- Arquivos SSTR ficam inacessíveis

## Soluções Testadas

### 1. SMB Share Mapping (incompleto)
- Share `\\192.168.0.21\SSTR` criado no app_ui.py
- startnet.cmd tenta mapear SMB
- Problema: Autenticação Guest no WinPE

### 2. httpdisk.sys (recomendado)
- Mesma técnica do iVentoy
- Monta ISO via HTTP como disco Y:
- Acessar SSTR via Y:\SSTR\

## Estado Atual
- boot.wim modificado com startnet.cmd customizado
- Menu.ipxe atualizado
- app_ui.py com SMB share automation

## Próximo Passo
Implementar httpdisk como no iVentoy.
