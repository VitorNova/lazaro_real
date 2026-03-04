/**
 * PM2 Ecosystem Configuration
 * Agente IA - Phant
 *
 * Comandos:
 *   pm2 start ecosystem.config.js
 *   pm2 restart agente-ia
 *   pm2 logs agente-ia
 *   pm2 stop agente-ia
 */

module.exports = {
  apps: [{
    // Nome do processo
    name: 'agente-ia',

    // Comando para executar (uvicorn via venv)
    script: '/var/www/phant/agente-ia/venv/bin/uvicorn',

    // Argumentos do uvicorn
    args: 'app.main:app --host 0.0.0.0 --port 3005',

    // Diretorio de trabalho
    cwd: '/var/www/phant/agente-ia',

    // Nao usar interpretador Node.js
    interpreter: 'none',

    // Numero de instancias (1 para FastAPI com async)
    instances: 1,

    // Modo de execucao
    exec_mode: 'fork',

    // Reiniciar automaticamente em caso de falha
    autorestart: true,

    // Nao monitorar arquivos (use --reload do uvicorn para dev)
    watch: false,

    // Reiniciar se memoria exceder 1GB
    max_memory_restart: '1G',

    // Variaveis de ambiente
    env: {
      NODE_ENV: 'production',
      APP_ENV: 'production',
      PORT: 3005
    },

    // Variaveis de ambiente para desenvolvimento
    env_development: {
      NODE_ENV: 'development',
      APP_ENV: 'development',
      PORT: 3005
    },

    // Arquivos de log
    error_file: '/root/.pm2/logs/agente-ia-error.log',
    out_file: '/root/.pm2/logs/agente-ia-out.log',

    // Formato da data nos logs
    log_date_format: 'YYYY-MM-DD HH:mm:ss Z',

    // Combinar logs stdout e stderr
    merge_logs: true,

    // Tempo de espera antes de considerar app como iniciado
    wait_ready: true,
    listen_timeout: 10000,

    // Tempo maximo para shutdown graceful
    kill_timeout: 5000,

    // Restart delay em caso de falha
    restart_delay: 1000,

    // Maximo de restarts em 15 minutos
    max_restarts: 10,
    min_uptime: '10s'
  }]
};
