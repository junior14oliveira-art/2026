# Aplicação das Heurísticas de Nielsen no 4MCSERVER

O design do painel de controle do **4MCSERVER** foi guiado pelas 10 Heurísticas de Usabilidade de Jakob Nielsen:

1.  **Visibilidade do Status do Sistema**: O painel mostra em tempo real se os serviços DHCP, TFTP e HTTP estão online com indicadores visuais (LEDs pulsantes).
2.  **Correspondência entre o Sistema e o Mundo Real**: Utilizamos termos técnicos familiares aos técnicos de TI (ISO, DHCP, PXE, Gateway) e ícones intuitivos.
3.  **Controle e Liberdade do Usuário**: Botões claros para iniciar/parar serviços e remover ISOs da biblioteca sem processos complexos.
4.  **Consistência e Padrões**: Seguimos o padrão de cores da indústria (Verde para sucesso/online, Vermelho para erro/offline, Azul para ações secundárias).
5.  **Prevenção de Erros**: O sistema valida se uma ISO foi "Preparada" antes de permitir o boot avançado, evitando falhas silenciosas no cliente.
6.  **Reconhecimento em vez de Memorização**: A lista de ISOs exibe o status de cada uma, eliminando a necessidade do usuário lembrar quais foram extraídas.
7.  **Flexibilidade e Eficiência de Uso**: Atalhos para adicionar ISOs por caminho direto ou scan automático da pasta.
8.  **Estética e Design Minimalista**: Interface "Deep Dark" com foco na informação essencial, evitando distrações visuais.
9.  **Ajuda os usuários a reconhecer, diagnosticar e recuperar erros**: Logs detalhados em tempo real traduzem erros de rede complexos em mensagens compreensíveis.
10. **Ajuda e Documentação**: Incluímos este guia e o README técnico diretamente na pasta raiz do projeto.
