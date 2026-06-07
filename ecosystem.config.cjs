// pm2 ecosystem config for Sonochron
// Run: pm2 start ecosystem.config.cjs
// Docs: https://pm2.keymetrics.io/docs/usage/application-declaration/

const PROJECT = '/home/jackc/projects/sonochron'

module.exports = {
  apps: [
    // ── Backend: FastAPI via Uvicorn ─────────────────────────────────
    {
      name: 'sonochron-api',
      cwd: `${PROJECT}/backend`,
      script: `${PROJECT}/backend/run.sh`,
      interpreter: 'bash',
      env: {
        DB_HOST: '192.168.0.201',
        DB_PORT: '5432',
        DB_USER: 'postgres',
        // DB_PASS is loaded from backend/.env via run.sh
        DB_NAME: 'sonochron',
        STORAGE_BASE_DIR: `${PROJECT}/backend/storage/raw`,
      },
      watch: false,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      error_file: `${PROJECT}/logs/api-error.log`,
      out_file: `${PROJECT}/logs/api-out.log`,
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
    },

  ],
}
