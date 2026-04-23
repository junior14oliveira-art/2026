# PXEGEMINI HTTPDisk Edition v5.7

Este projeto e o meu PXE local no estilo iVentoy, montado a partir das ideias e ferramentas que ja estavam na bancada:

- `E:\iventoy-1.0.21`
- `E:\PXE-WIMBOOT`
- `E:\4mc-pxe-server`
- `E:\PXEGEMINI`

O foco e o mesmo uso pratico do iVentoy em bancada tecnica:

- boot PXE de WinPE e Strelec
- compatibilidade com Dell e Lenovo
- modo `DHCP` ou `ProxyDHCP`
- menus gerados automaticamente
- montagem de ISO via `HTTPDisk`
- fallback para SMB quando necessario
- selecao de adaptador de rede com preenchimento automatico do IP
- filtro de adaptadores virtuais e loopback para reduzir ruido
- preparo automatico da biblioteca da pasta configurada ao trocar de adaptador
- preparacao completa manual para varrer todos os discos quando necessario
- controle de revisao do menu e historico de versao na UI

## O que este projeto faz

- entrega `undionly.kpxe`, `snponly.efi`, `ipxe.efi` e `wimboot` por TFTP/HTTP
- gera `menu.ipxe` dinamicamente com as ISOs adicionadas
- gera `boot.ipxe` e `autoexec.ipxe` como fallback para chainload do iPXE
- serve ISOs originais pela rota `*_raw.iso`
- monta a ISO no WinPE com `httpdisk.exe` + `httpdisk.sys`
- executa `MInst.exe` e outros utilitarios do `SSTR`
- registra diagnostico da cadeia de boot

## Fluxo de boot

1. O firmware chama o servidor PXE.
2. O servidor responde com `undionly.kpxe` no BIOS ou `snponly.efi` / `ipxe.efi` no UEFI.
3. O cliente iPXE carrega `boot.ipxe` ou `autoexec.ipxe` e segue para o `menu.ipxe`.
4. A entrada WinPE usa `wimboot` para subir `boot.wim`, `BCD` e `boot.sdi`.
5. O `startnet.cmd` monta a ISO por `HTTPDisk`.
6. O WinPE enxerga a ISO como disco `Y:` e abre os utilitarios.
7. A escolha do adaptador prepara a pasta configurada e atualiza o menu.

## Perfis incluidos

- `auto`
- `dell`
- `lenovo`
- `isolated`
- `mixed`

## Controle de versao

- `app_version` identifica a edicao atual da interface.
- `menu_version` sobe a cada geracao do `menu.ipxe`.
- `last_menu_generated` registra a ultima atualizacao do menu.
- A aba `Releases` mostra o historico da evolucao do projeto.

## Pastas importantes

- `boot/`: arquivos de boot, `menu.ipxe`, `httpdisk.exe`, `httpdisk.sys`, `wimboot`
- `data/extracted/`: conteudo extraido das ISOs
- `servers/`: implementacao de `DHCP`, `TFTP` e `HTTP`
- `docs/`: analises e notas de laboratorio

## Como usar

1. Abra `main.py` ou o atalho de inicializacao.
2. Defina o IP do servidor.
3. Escolha o adaptador de rede correto.
4. Deixe `Preparar ISO automaticamente` ligado para preparar a pasta configurada quando escolher o adaptador.
5. Escolha `ProxyDHCP` se ja existir outro DHCP na rede.
6. Selecione o perfil `auto`, `dell` ou `lenovo`.
7. Escolha `isolated` para bancada direta ou `mixed` para rede comum.
8. Use `Scanear Discos` se quiser varrer tudo manualmente.
9. Adicione ou escaneie ISOs.
10. Inicie o servidor e faca o boot no notebook.

## Observacao

Este nao e o iVentoy original. E uma implementacao local inspirada no fluxo dele, com a tecnica de `HTTPDisk` para evitar depender de menu ISO e manter a ISO acessivel no WinPE.
