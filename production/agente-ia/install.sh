#!/bin/bash
# =============================================================================
# SCRIPT DE INSTALACAO - AGENTE IA
# =============================================================================
set -e

echo "============================================"
echo "  INSTALACAO DO AGENTE IA - PHANT"
echo "============================================"
echo ""

# Cores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Diretorio do projeto
PROJECT_DIR="/var/www/phant/agente-ia"
cd "$PROJECT_DIR"

# Verifica Python
echo -e "${YELLOW}Verificando Python...${NC}"
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    echo -e "${GREEN}Python $PYTHON_VERSION encontrado${NC}"
else
    echo -e "${RED}Python 3 nao encontrado. Instale Python 3.11+${NC}"
    exit 1
fi

# Cria ambiente virtual
echo ""
echo -e "${YELLOW}Criando ambiente virtual...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}Ambiente virtual criado${NC}"
else
    echo -e "${GREEN}Ambiente virtual ja existe${NC}"
fi

# Ativa ambiente virtual
source venv/bin/activate

# Atualiza pip
echo ""
echo -e "${YELLOW}Atualizando pip...${NC}"
pip install --upgrade pip > /dev/null

# Instala dependencias
echo ""
echo -e "${YELLOW}Instalando dependencias...${NC}"
pip install -r requirements.txt

# Cria .env se nao existir
echo ""
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}Criando .env a partir do .env.example...${NC}"
    cp .env.example .env
    echo -e "${RED}ATENCAO: Configure as variaveis em .env antes de iniciar!${NC}"
else
    echo -e "${GREEN}Arquivo .env ja existe${NC}"
fi

# Cria diretorio de logs
mkdir -p logs

echo ""
echo "============================================"
echo -e "${GREEN}  INSTALACAO CONCLUIDA!${NC}"
echo "============================================"
echo ""
echo "Proximos passos:"
echo ""
echo "  1. Edite o arquivo .env com suas credenciais:"
echo "     nano .env"
echo ""
echo "  2. Ative o ambiente virtual:"
echo "     source venv/bin/activate"
echo ""
echo "  3. Execute em modo desenvolvimento:"
echo "     uvicorn app.main:app --reload --host 0.0.0.0 --port 3003"
echo ""
echo "  4. Ou inicie com PM2 (producao):"
echo "     pm2 start ecosystem.config.js"
echo ""
echo "  5. Verifique a saude da aplicacao:"
echo "     curl http://localhost:3003/health"
echo ""
