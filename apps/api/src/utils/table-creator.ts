/**
 * SQL generators para criar tabelas dinamicas do agente
 */

/**
 * Gera SQL para criar tabela de leads (LeadboxCRM_*)
 */
export function createLeadTableSQL(tableName: string): string {
  return `
    CREATE TABLE IF NOT EXISTS "${tableName}" (
      id SERIAL PRIMARY KEY,
      nome TEXT,
      telefone TEXT,
      email TEXT,
      empresa TEXT,
      ad_url TEXT,
      pacote TEXT,
      resumo TEXT,
      pipeline_step TEXT DEFAULT 'Leads',
      valor NUMERIC,
      status TEXT DEFAULT 'open',
      close_date TIMESTAMPTZ,
      lead_origin TEXT,
      responsavel TEXT DEFAULT 'AI',
      remotejid TEXT UNIQUE,
      follow_count INTEGER DEFAULT 0,
      updated_date TIMESTAMPTZ DEFAULT NOW(),
      created_date TIMESTAMPTZ DEFAULT NOW(),
      venda_realizada TEXT,
      "Atendimento_Finalizado" TEXT DEFAULT 'false',
      -- Handoff tracking (when AI pauses and human takes over)
      current_state TEXT DEFAULT 'ai',
      paused_at TIMESTAMPTZ,
      paused_by TEXT,
      resumed_at TIMESTAMPTZ,
      handoff_at TIMESTAMPTZ,
      handoff_reason TEXT,
      handoff_priority TEXT,
      handoff_department TEXT,
      -- Human conversation tracking (messages after AI pause)
      last_human_message_at TIMESTAMPTZ,
      human_message_count INTEGER DEFAULT 0,
      -- Follow_01 a Follow_09 removidos (dead code - nunca usados)
      ultimo_intent TEXT,
      crm TEXT,
      -- Asaas integration fields
      asaas_customer_id TEXT,
      cpf_cnpj TEXT,
      -- BANT qualification fields
      bant_budget INTEGER DEFAULT 0,
      bant_authority INTEGER DEFAULT 0,
      bant_need INTEGER DEFAULT 0,
      bant_timing INTEGER DEFAULT 0,
      bant_total INTEGER DEFAULT 0,
      bant_notes TEXT,
      qualification_score INTEGER DEFAULT 0,
      lead_temperature TEXT DEFAULT 'frio',
      -- Multi-agent support
      current_agent_id UUID,
      current_agent_name TEXT,
      -- Conversation history (sync from messages table)
      conversation_history JSONB,
      -- Scheduling fields (synced from schedules table)
      next_appointment_at TIMESTAMPTZ,
      next_appointment_link TEXT,
      last_scheduled_at TIMESTAMPTZ,
      -- Agent journey tracking
      attended_by TEXT,
      journey_stage TEXT DEFAULT 'lead',
      -- Observer insights (AI-extracted data from conversations)
      insights JSONB DEFAULT '{}'::jsonb
    );

    CREATE INDEX IF NOT EXISTS "${tableName}_remotejid_idx" ON "${tableName}" (remotejid);
    CREATE INDEX IF NOT EXISTS "${tableName}_current_agent_id_idx" ON "${tableName}" (current_agent_id);
    CREATE INDEX IF NOT EXISTS "${tableName}_pipeline_step_idx" ON "${tableName}" (pipeline_step);
    CREATE INDEX IF NOT EXISTS "${tableName}_status_idx" ON "${tableName}" (status);
    CREATE INDEX IF NOT EXISTS "${tableName}_created_date_idx" ON "${tableName}" (created_date);
    CREATE INDEX IF NOT EXISTS "${tableName}_next_appointment_idx" ON "${tableName}" (next_appointment_at) WHERE next_appointment_at IS NOT NULL;
    CREATE INDEX IF NOT EXISTS "${tableName}_journey_stage_idx" ON "${tableName}" (journey_stage);

    -- Habilitar Supabase Realtime para atualizacoes em tempo real no CRM
    ALTER TABLE "${tableName}" REPLICA IDENTITY FULL;
  `;
}

/**
 * Gera SQL para criar tabela de mensagens (leadbox_messages_*)
 */
export function createMessagesTableSQL(tableName: string): string {
  return `
    CREATE TABLE IF NOT EXISTS "${tableName}" (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      creat TIMESTAMPTZ DEFAULT NOW(),
      remotejid TEXT UNIQUE NOT NULL,
      conversation_history JSONB,
      "Msg_model" TIMESTAMPTZ,
      "Msg_user" TIMESTAMPTZ
    );

    CREATE INDEX IF NOT EXISTS "${tableName}_remotejid_idx" ON "${tableName}" (remotejid);
    CREATE INDEX IF NOT EXISTS "${tableName}_creat_idx" ON "${tableName}" (creat);
  `;
}

/**
 * @deprecated table_controle não é mais usado - agendamentos e pagamentos
 * são armazenados nas tabelas globais 'schedules' e 'payments'
 */
export function createControleTableSQL(tableName: string): string {
  return `-- table_controle deprecated`;
}

/**
 * Gera SQL para criar tabela de buffer temporário de mensagens (msg_temp_*)
 * Usado para acumular mensagens sequenciais antes de processar com IA
 * Segue lógica do N8N: aguarda delay sem novas mensagens antes de processar
 *
 * ATUALIZAÇÃO v2: Agora suporta mídia (imagens, áudios, vídeos, documentos)
 * - media_type: tipo da mídia (image, audio, video, document)
 * - media_mime_type: MIME type (image/jpeg, audio/ogg, etc)
 * - media_message_id: ID da mensagem para baixar mídia depois
 * - media_url: URL da mídia criptografada (WhatsApp)
 * - media_key: Chave para decriptação da mídia (base64)
 * - file_sha256: Hash SHA256 do arquivo (base64)
 * - file_length: Tamanho do arquivo em bytes
 */
export function createMsgTempTableSQL(tableName: string): string {
  return `
    CREATE TABLE IF NOT EXISTS "${tableName}" (
      id SERIAL PRIMARY KEY,
      "TextMessage" TEXT NOT NULL,
      "remoteJid" TEXT NOT NULL,
      "ID" TEXT NOT NULL,
      timestamp INTEGER NOT NULL,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      -- Colunas para suporte a mídia (v2)
      media_type TEXT,
      media_mime_type TEXT,
      media_message_id TEXT,
      media_url TEXT,
      -- Colunas adicionais para download de mídia (v3)
      media_key TEXT,
      file_sha256 TEXT,
      file_length INTEGER
    );

    CREATE INDEX IF NOT EXISTS "${tableName}_remotejid_idx" ON "${tableName}" ("remoteJid");
    CREATE INDEX IF NOT EXISTS "${tableName}_timestamp_idx" ON "${tableName}" (timestamp);
  `;
}

/**
 * Gera SQL para migrar tabela msg_temp existente (adicionar colunas de mídia)
 * Usado para tabelas criadas antes da atualização de suporte a mídia
 */
export function migrateMsgTempTableSQL(tableName: string): string {
  return `
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS media_type TEXT;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS media_mime_type TEXT;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS media_message_id TEXT;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS media_url TEXT;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS media_key TEXT;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS file_sha256 TEXT;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS file_length INTEGER;
  `;
}

/**
 * Gera SQL para migrar tabela de leads existente (adicionar colunas faltantes)
 * Usado para tabelas criadas antes das atualizações de multi-agent e conversation_history
 */
export function migrateLeadTableSQL(tableName: string): string {
  return `
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS current_agent_id UUID;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS current_agent_name TEXT;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS conversation_history JSONB;
    CREATE INDEX IF NOT EXISTS "${tableName}_current_agent_id_idx" ON "${tableName}" (current_agent_id);
  `;
}

/**
 * Gera SQL para adicionar colunas de agendamento em tabelas existentes
 * Sincroniza dados da tabela schedules para LeadboxCRM
 */
export function migrateLeadTableSchedulingSQL(tableName: string): string {
  return `
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS next_appointment_at TIMESTAMPTZ;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS next_appointment_link TEXT;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS last_scheduled_at TIMESTAMPTZ;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS attended_by TEXT;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS journey_stage TEXT DEFAULT 'lead';
    CREATE INDEX IF NOT EXISTS "${tableName}_next_appointment_idx" ON "${tableName}" (next_appointment_at) WHERE next_appointment_at IS NOT NULL;
    CREATE INDEX IF NOT EXISTS "${tableName}_journey_stage_idx" ON "${tableName}" (journey_stage);
  `;
}

/**
 * Gera SQL para adicionar colunas de handoff tracking em tabelas existentes
 * Permite rastrear quando o atendimento foi pausado (IA -> humano)
 */
export function migrateLeadTableHandoffSQL(tableName: string): string {
  return `
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS current_state TEXT DEFAULT 'ai';
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS paused_at TIMESTAMPTZ;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS paused_by TEXT;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS resumed_at TIMESTAMPTZ;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS handoff_at TIMESTAMPTZ;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS handoff_reason TEXT;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS handoff_priority TEXT;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS handoff_department TEXT;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS last_human_message_at TIMESTAMPTZ;
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS human_message_count INTEGER DEFAULT 0;
    CREATE INDEX IF NOT EXISTS "${tableName}_paused_at_idx" ON "${tableName}" (paused_at) WHERE paused_at IS NOT NULL;
    CREATE INDEX IF NOT EXISTS "${tableName}_human_msg_idx" ON "${tableName}" (last_human_message_at) WHERE last_human_message_at IS NOT NULL;
  `;
}

/**
 * Gera SQL para adicionar colunas de timezone/localização do lead
 * Permite detectar fuso horário para agendamentos corretos
 */
export function migrateLeadTableTimezoneSQL(tableName: string): string {
  return `
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS cidade VARCHAR(100);
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS estado VARCHAR(2);
    ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS timezone VARCHAR(50);
  `;
}

/**
 * Gera SQL para adicionar coluna insights em tabelas existentes
 * Armazena dados extraídos pelo Observer durante conversas
 */
export function migrateLeadTableInsightsSQL(tableName: string): string {
  return `ALTER TABLE "${tableName}" ADD COLUMN IF NOT EXISTS insights JSONB DEFAULT '{}'::jsonb;`;
}

/**
 * Gera SQL para habilitar Supabase Realtime em tabelas existentes
 * Configura REPLICA IDENTITY FULL e adiciona a tabela na publicacao supabase_realtime
 *
 * IMPORTANTE: A publicacao 'supabase_realtime' deve existir no banco de dados.
 * No Supabase, ela ja existe por padrao. Para bancos locais, criar com:
 * CREATE PUBLICATION supabase_realtime FOR ALL TABLES;
 */
export function enableRealtimeForLeadTableSQL(tableName: string): string {
  return `
    -- Habilitar REPLICA IDENTITY FULL para capturar OLD values em DELETE/UPDATE
    ALTER TABLE "${tableName}" REPLICA IDENTITY FULL;

    -- Adicionar tabela na publicacao supabase_realtime (ignora se ja existe)
    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime' AND tablename = '${tableName}'
      ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE "${tableName}";
      END IF;
    EXCEPTION
      WHEN undefined_object THEN
        -- Publicacao nao existe, criar uma nova
        CREATE PUBLICATION supabase_realtime FOR TABLE "${tableName}";
    END $$;
  `;
}

/**
 * Gera SQL para dropar tabelas (usado em rollback)
 */
export function dropTablesSQL(
  leadsTable: string,
  messagesTable: string,
  msgTempTable?: string | null
): string {
  let sql = `
    DROP TABLE IF EXISTS "${leadsTable}" CASCADE;
    DROP TABLE IF EXISTS "${messagesTable}" CASCADE;
  `;
  if (msgTempTable) {
    sql += `DROP TABLE IF EXISTS "${msgTempTable}" CASCADE;`;
  }
  return sql;
}

/**
 * Gera todos os SQLs de criacao de tabelas
 */
export function createAllTablesSQL(
  leadsTable: string,
  messagesTable: string,
  msgTempTable?: string | null
): string {
  let sql = `
    ${createLeadTableSQL(leadsTable)}
    ${createMessagesTableSQL(messagesTable)}
  `;
  if (msgTempTable) {
    sql += createMsgTempTableSQL(msgTempTable);
  }
  return sql;
}

/**
 * Gera SQL para criar tabela DIANA unificada
 * Tabela central para prospecção multi-agente:
 * - Agent 1: Encontra o decisor
 * - Agent 2: Gera interesse no decisor
 *
 * NOTA: Esta tabela é global e já deve existir no banco.
 * Esta função é mantida para referência e possíveis recriações.
 */
export function createDianaTablesSQL(): string {
  return `
    -- ============================================================================
    -- TABELA DIANA UNIFICADA
    -- Tabela central para prospecção multi-agente
    -- ============================================================================

    CREATE TABLE IF NOT EXISTS diana (
      -- IDENTIFICAÇÃO
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,

      -- DADOS DO PROSPECT/EMPRESA
      empresa TEXT NOT NULL,
      telefone TEXT NOT NULL,
      telefone_formatado TEXT NOT NULL,
      remotejid TEXT,
      endereco TEXT,
      cidade TEXT,
      estado TEXT,
      website TEXT,
      categoria TEXT,
      rating DECIMAL(2,1),
      total_avaliacoes INTEGER,

      -- DECISOR (preenchido pelo Agent 1)
      decisor_nome TEXT,
      decisor_cargo TEXT,
      decisor_confirmado BOOLEAN DEFAULT FALSE,

      -- AGENT 1 - ENCONTRAR DECISOR
      agent1_status TEXT DEFAULT 'pending',
      agent1_mensagens_enviadas INTEGER DEFAULT 0,
      agent1_ultima_mensagem_at TIMESTAMPTZ,
      agent1_proxima_mensagem_at TIMESTAMPTZ,
      agent1_historico JSONB DEFAULT '[]',

      -- AGENT 2 - GERAR INTERESSE
      agent2_ready BOOLEAN DEFAULT FALSE,
      agent2_status TEXT DEFAULT 'pending',
      agent2_mensagens_enviadas INTEGER DEFAULT 0,
      agent2_ultima_mensagem_at TIMESTAMPTZ,
      agent2_proxima_mensagem_at TIMESTAMPTZ,
      agent2_historico JSONB DEFAULT '[]',

      -- PIPELINE / CRM
      pipeline_step TEXT DEFAULT 'prospect_novo',

      -- QUALIFICAÇÃO BANT
      bant_budget INTEGER DEFAULT 0,
      bant_authority INTEGER DEFAULT 0,
      bant_need INTEGER DEFAULT 0,
      bant_timing INTEGER DEFAULT 0,
      bant_total INTEGER DEFAULT 0,
      bant_notes TEXT,
      lead_temperature TEXT DEFAULT 'frio',

      -- TRANSFERÊNCIA
      transferred_to TEXT,
      transferred_at TIMESTAMPTZ,
      transfer_notes TEXT,

      -- ORIGEM / METADATA
      source TEXT DEFAULT 'google_places',
      place_id TEXT,
      metadata JSONB DEFAULT '{}',
      tags TEXT[],

      -- CONTROLE
      created_at TIMESTAMPTZ DEFAULT NOW(),
      updated_at TIMESTAMPTZ DEFAULT NOW(),

      UNIQUE(agent_id, telefone_formatado)
    );

    -- ÍNDICES
    CREATE INDEX IF NOT EXISTS idx_diana_agent_id ON diana(agent_id);
    CREATE INDEX IF NOT EXISTS idx_diana_agent1_status ON diana(agent1_status);
    CREATE INDEX IF NOT EXISTS idx_diana_agent2_ready ON diana(agent_id, agent2_ready) WHERE agent2_ready = TRUE;
    CREATE INDEX IF NOT EXISTS idx_diana_pipeline ON diana(pipeline_step);
    CREATE INDEX IF NOT EXISTS idx_diana_telefone ON diana(telefone_formatado);
    CREATE INDEX IF NOT EXISTS idx_diana_remotejid ON diana(remotejid);
  `;
}
