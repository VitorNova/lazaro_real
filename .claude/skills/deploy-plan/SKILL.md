---
name: deploy-plan
description: Cria plano de deploy seguro para o lazaro-real. Use antes de qualquer
  mudança em produção, migração de código, ou quando precisar trocar o PM2.
---

# Deploy Plan — Lazaro-Real

Você conhece toda a arquitetura pelo CLAUDE.md. Antes de criar o plano:

## 1. Mapear divergências
Compare o estado atual do código com produção:
```bash
cd /var/www/lazaro-real && git log --oneline -10
pm2 show lazaro-ia | grep -iE "script|cwd|uptime"
```

## 2. Identificar impacto
- 🔴 **Crítico** — afeta webhook WhatsApp (Ana para de responder imediatamente)
- 🟡 **Alto** — afeta jobs (billing/manutenção não disparam)
- 🟢 **Baixo** — afeta painel, API, sem impacto na Ana

## 3. Plano mínimo seguro
Todo deploy deve ter:
1. py_compile em todos os arquivos alterados
2. Janela fora de seg-sex 8h-10h (horário dos jobs)
3. Rollback disponível: phant porta 3005 continua de pé
4. Teste pós-deploy:
```bash
sleep 5
curl -s http://127.0.0.1:3115/health
pm2 logs lazaro-ia --lines 20 --nostream | grep -iE "started|error|scheduler"
```

## 4. Formato do plano
```
MUDANÇA: [descrição]
IMPACTO: 🔴/🟡/🟢
JANELA:  [horário recomendado]

Passos:
1. [pré-validação]
2. [aplicar mudança]
3. [restart se necessário]
4. [verificação pós]
5. [rollback se falhar]

Rollback: pm2 restart agente-ia (volta para phant)
```
