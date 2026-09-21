# Deploy ativo — Hostinger VPS + Cloudflare Tunnel (quick tunnel)

Registro do deploy real em produção pessoal/demo, feito a pedido explícito do usuário (login pelo
navegador + hospedagem imediata, sem domínio próprio). Não é a recomendação padrão deste dossiê
para produção multi-cliente — ver ressalvas no fim.

## Topologia

- **VPS**: Hostinger `srv1747747.hstgr.cloud` (2.25.196.22) — já hospeda o stack Supabase do
  projeto `cedroleads` (13 containers); o MCP roda isolado, sem tocar nisso.
- **Imagem**: `ghcr.io/t4msy/cedro-mcp-server:latest`, publicada por
  `.github/workflows/docker-publish.yml` a cada push em `master` (repositório público:
  `github.com/T4Msy/cedro-mcp-server` — sem segredos no código, `.env` fica de fora do git).
- **Deploy na VPS**: via API de Docker Compose da Hostinger (`mcp__hostinger-vps__VPS_*`), não
  SSH — o acesso SSH direto não estava alcançável (timeout mesmo com a porta liberada no
  firewall; a via que funcionou de verdade foi a API de projetos Docker).
- **Dois projetos Docker Compose separados, de propósito:**
  1. **`cedro-mcp`** — só o `app` (o servidor MCP), publicado em `8000:8000` (alcançável só
     dentro da rede da VPS — a porta 8000 **não** está liberada no firewall da Hostinger pro
     público). Redeploy livre a qualquer momento (nova imagem, nova env var) sem afetar o túnel.
  2. **`cedro-mcp-tunnel`** — só o `cloudflared`, apontando pra
     `http://host.docker.internal:8000` (via `extra_hosts: host.docker.internal:host-gateway`).
     **Nunca redeployar sem necessidade** — cada `docker compose up` deste projeto reinicia o
     `cloudflared` e gera uma URL **nova** (é um *quick tunnel*, efêmero por natureza).

Essa separação existe porque a API de deploy da Hostinger recria o projeto inteiro a cada chamada
(não faz diff por serviço como um `docker compose up` local faria) — colocar os dois serviços no
mesmo projeto significa que qualquer atualização do `app` também troca a URL pública do túnel.

## URL pública atual

`https://skating-committees-during-monica.trycloudflare.com` (`/mcp` para o endpoint MCP).

⚠️ **Muda se o container `cedro-mcp-tunnel-cloudflared-1` for reiniciado** (redeploy do projeto
`cedro-mcp-tunnel`, reboot da VPS, etc.) — é a natureza de um *quick tunnel* sem conta Cloudflare.
Se isso acontecer: ler os logs do projeto `cedro-mcp-tunnel` pra pegar a nova URL, e redeployar o
projeto `cedro-mcp` com `MCP_RESOURCE_URL`/`MCP_ALLOWED_HOSTS`/`MCP_ALLOWED_ORIGINS` atualizados.

## Como redeployar o `app` (nova imagem/env, sem afetar o túnel)

1. Push em `master` do repo `github.com/T4Msy/cedro-mcp-server` → `.github/workflows/
   docker-publish.yml` builda e publica `ghcr.io/t4msy/cedro-mcp-server:latest` sozinho
   (conferir com `gh run list --workflow=docker-publish.yml --limit 1`).
2. Chamar `mcp__hostinger-vps__VPS_createNewProjectV1` com `virtualMachineId: 1747747`,
   `project_name: "cedro-mcp"` e este compose (troque a URL se o túnel tiver mudado — ver
   seção acima):

```yaml
services:
  app:
    image: ghcr.io/t4msy/cedro-mcp-server:latest
    restart: unless-stopped
    pull_policy: always
    environment:
      MCP_TRANSPORT: streamable-http
      MCP_HOST: 0.0.0.0
      MCP_PORT: "8000"
      MCP_WEB_LOGIN: "true"
      # Socket Crystal TCP (Fase 2): homologação ou produção com failover.
      # CEDRO_CRYSTAL_HOST: "datafeed1.cedrotech.com,datafeed2.cedrotech.com"
      # CEDRO_CRYSTAL_PORT: "81"
      MCP_RESOURCE_URL: "https://skating-committees-during-monica.trycloudflare.com/mcp"
      MCP_ALLOWED_HOSTS: "skating-committees-during-monica.trycloudflare.com"
      MCP_ALLOWED_ORIGINS: "https://skating-committees-during-monica.trycloudflare.com"
    ports:
      - "8000:8000"
```

3. Confirmar com `curl -s https://<url-do-tunel>/.well-known/oauth-authorization-server` — se
   voltar JSON com `scopes_supported`, subiu certo.

⚠️ **Todo redeploy do `app` derruba a sessão de quem já tinha logado** (credenciais em memória,
ver `06-credential-transport.md`) — o usuário precisa reconectar/reautenticar no cliente MCP
depois. Evite redeployar sem necessidade real enquanto alguém estiver testando ativamente.

## Ressalvas registradas (ver também `06-credential-transport.md`)

- **Sem uptime garantido**: quick tunnel é para teste/demo, não produção crítica (aviso do
  próprio `cloudflared` nos logs). Pra produção de verdade: túnel nomeado com conta Cloudflare
  (URL estável, sem esse problema de redeploy).
- **Processo único**: as credenciais logadas via `/cedro-login` ficam em memória do processo
  `app` — reiniciar o container desloga todo mundo (ver `06-credential-transport.md`).
- **Streaming Fase 2**: mantenha **uma única réplica** de `app` para cada credencial Socket Crystal. O
  conector/cache é local ao processo e subir réplicas paralelas pode abrir logins simultâneos para a
  mesma conta, causando desconexão ou bloqueio pela Cedro. Só habilitar `CEDRO_CRYSTAL_HOST` depois de
  configurar a credencial e concluir o gate real.
- `CEDRO_DOCS_PATH` não foi configurado neste deploy — `cedro-docs://` fica vazio (a skill
  `market-data-rest` não está na imagem; seria preciso vendorizá-la no repo pra incluir).
