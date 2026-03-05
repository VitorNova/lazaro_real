module.exports = {
  apps: [{
    name: 'lazaro-ia',
    script: '/var/www/phant/agente-ia/venv/bin/uvicorn',
    args: 'app.main:app --host 0.0.0.0 --port 3006',
    cwd: '/var/www/lazaro-real/apps/ia',
    interpreter: 'none',
    env: {
      PYTHONPATH: '/var/www/lazaro-real/apps/ia'
    },
    max_memory_restart: '1G',
    error_file: '/root/.pm2/logs/lazaro-ia-error.log',
    out_file: '/root/.pm2/logs/lazaro-ia-out.log',
  }]
}
