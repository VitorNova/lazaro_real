import { SupabaseClient } from '@supabase/supabase-js';
import { supabaseAdmin } from '../client';
import {
  DynamicLead,
  DynamicLeadCreate,
  DynamicLeadUpdate,
  LeadMessage,
  LeadMessageCreate,
  LeadMessageUpdate,
  Controle,
  ControleCreate,
  ControleUpdate,
} from '../types';

// Logger simples para o repository
const Logger = {
  info: (message: string, data?: unknown) => {
    console.log(`[DynamicRepository] ${message}`, data ? JSON.stringify(data, null, 2) : '');
  },
  error: (message: string, error?: unknown) => {
    console.error(`[DynamicRepository] ${message}`, error);
  },
  debug: (message: string, data?: unknown) => {
    if (process.env.DEBUG === 'true') {
      console.log(`[DynamicRepository:DEBUG] ${message}`, data ? JSON.stringify(data, null, 2) : '');
    }
  },
};

export class DynamicRepository {
  private supabase: SupabaseClient;

  constructor(supabase?: SupabaseClient) {
    this.supabase = supabase || supabaseAdmin;
  }

  // ============================================================================
  // LEADS (tabelas LeadboxCRM_*)
  // ============================================================================

  async findLeadByRemoteJid(tableName: string, remotejid: string): Promise<DynamicLead | null> {
    try {
      Logger.debug(`Finding lead in ${tableName} by remotejid: ${remotejid}`);

      const { data, error } = await this.supabase
        .from(tableName)
        .select('*')
        .eq('remotejid', remotejid)
        .single();

      if (error) {
        if (error.code === 'PGRST116') {
          Logger.debug(`No lead found in ${tableName} for remotejid: ${remotejid}`);
          return null;
        }
        Logger.error(`Error finding lead in ${tableName}`, error);
        throw new Error(`Failed to find lead: ${error.message}`);
      }

      return data;
    } catch (error) {
      Logger.error(`Exception finding lead in ${tableName}`, error);
      throw error;
    }
  }

  /**
   * Busca lead pelo número de telefone
   * Útil para encontrar leads que foram criados com @lid e precisam ser unificados
   */
  async findLeadByPhone(tableName: string, telefone: string): Promise<DynamicLead | null> {
    try {
      Logger.debug(`Finding lead in ${tableName} by telefone: ${telefone}`);

      const { data, error } = await this.supabase
        .from(tableName)
        .select('*')
        .eq('telefone', telefone)
        .single();

      if (error) {
        if (error.code === 'PGRST116') {
          Logger.debug(`No lead found in ${tableName} for telefone: ${telefone}`);
          return null;
        }
        Logger.error(`Error finding lead by phone in ${tableName}`, error);
        throw new Error(`Failed to find lead by phone: ${error.message}`);
      }

      return data;
    } catch (error) {
      Logger.error(`Exception finding lead by phone in ${tableName}`, error);
      throw error;
    }
  }

  async findLeadById(tableName: string, id: number): Promise<DynamicLead | null> {
    try {
      Logger.debug(`Finding lead in ${tableName} by id: ${id}`);

      const { data, error } = await this.supabase
        .from(tableName)
        .select('*')
        .eq('id', id)
        .single();

      if (error) {
        if (error.code === 'PGRST116') {
          Logger.debug(`No lead found in ${tableName} for id: ${id}`);
          return null;
        }
        Logger.error(`Error finding lead by id in ${tableName}`, error);
        throw new Error(`Failed to find lead: ${error.message}`);
      }

      return data;
    } catch (error) {
      Logger.error(`Exception finding lead by id in ${tableName}`, error);
      throw error;
    }
  }

  async createLead(tableName: string, data: DynamicLeadCreate): Promise<DynamicLead> {
    try {
      const now = new Date().toISOString();
      const leadData = {
        ...data,
        created_date: now,
        updated_date: now,
      };

      Logger.debug(`Creating lead in ${tableName}`, leadData);

      const { data: lead, error } = await this.supabase
        .from(tableName)
        .insert(leadData)
        .select()
        .single();

      if (error) {
        Logger.error(`Error creating lead in ${tableName}`, error);
        throw new Error(`Failed to create lead: ${error.message}`);
      }

      Logger.info(`Lead created in ${tableName} with id: ${lead.id}`);
      return lead;
    } catch (error) {
      Logger.error(`Exception creating lead in ${tableName}`, error);
      throw error;
    }
  }

  async updateLead(tableName: string, id: number, data: DynamicLeadUpdate): Promise<DynamicLead> {
    try {
      const updateData = {
        ...data,
        updated_date: new Date().toISOString(),
      };

      Logger.debug(`Updating lead ${id} in ${tableName}`, updateData);

      const { data: lead, error } = await this.supabase
        .from(tableName)
        .update(updateData)
        .eq('id', id)
        .select()
        .single();

      if (error) {
        Logger.error(`Error updating lead in ${tableName}`, error);
        throw new Error(`Failed to update lead: ${error.message}`);
      }

      Logger.info(`Lead ${id} updated in ${tableName}`);
      return lead;
    } catch (error) {
      Logger.error(`Exception updating lead in ${tableName}`, error);
      throw error;
    }
  }

  async updateLeadByRemoteJid(tableName: string, remotejid: string, data: DynamicLeadUpdate): Promise<DynamicLead> {
    try {
      const updateData = {
        ...data,
        updated_date: new Date().toISOString(),
      };

      Logger.debug(`Updating lead by remotejid ${remotejid} in ${tableName}`, updateData);

      const { data: lead, error } = await this.supabase
        .from(tableName)
        .update(updateData)
        .eq('remotejid', remotejid)
        .select()
        .single();

      if (error) {
        Logger.error(`Error updating lead by remotejid in ${tableName}`, error);
        throw new Error(`Failed to update lead: ${error.message}`);
      }

      Logger.info(`Lead updated by remotejid ${remotejid} in ${tableName}`);
      return lead;
    } catch (error) {
      Logger.error(`Exception updating lead by remotejid in ${tableName}`, error);
      throw error;
    }
  }

  async getOrCreateLead(tableName: string, remotejid: string, defaultData?: DynamicLeadCreate): Promise<DynamicLead> {
    // 1. Primeiro, buscar pelo remotejid exato
    const existing = await this.findLeadByRemoteJid(tableName, remotejid);
    if (existing) {
      // Se o lead existe mas não tem nome, e temos pushName, atualizar
      const hasNoName = !existing.nome || existing.nome.trim() === '' || existing.nome.match(/^\(\d{2}\)\s?\d{4,5}-?\d{3,4}$/);
      const hasPushName = defaultData?.nome && defaultData.nome.trim() !== '';

      if (hasNoName && hasPushName) {
        Logger.info(`[PushName Update] Updating lead name from pushName`, {
          tableName,
          leadId: existing.id,
          oldName: existing.nome,
          newName: defaultData.nome
        });

        const updated = await this.updateLead(tableName, existing.id, {
          nome: defaultData.nome
        });

        return updated || existing;
      }

      return existing;
    }

    // 2. Se não encontrou e o remotejid é um número WhatsApp válido (@s.whatsapp.net),
    //    buscar pelo telefone para evitar duplicação de leads que vieram via @lid
    if (remotejid.endsWith('@s.whatsapp.net')) {
      const telefone = remotejid.replace('@s.whatsapp.net', '');

      // Buscar lead pelo telefone
      const existingByPhone = await this.findLeadByPhone(tableName, telefone);

      if (existingByPhone) {
        // Se encontrou um lead pelo telefone, verificar se o remotejid antigo era @lid
        // Se sim, atualizar o remotejid para o formato correto @s.whatsapp.net
        if (existingByPhone.remotejid && existingByPhone.remotejid.endsWith('@lid')) {
          const oldLidRemoteJid = existingByPhone.remotejid;

          Logger.info(`[Lead Unification] Found lead by phone with @lid, updating remotejid`, {
            tableName,
            leadId: existingByPhone.id,
            oldRemoteJid: oldLidRemoteJid,
            newRemoteJid: remotejid,
            telefone
          });

          // Atualizar o remotejid do lead existente
          const updatedLead = await this.updateLead(tableName, existingByPhone.id, {
            remotejid: remotejid,
          });

          // Também atualizar o remotejid nas mensagens para manter consistência
          // A tabela de mensagens segue o padrão: leadbox_messages_AGENTID
          // tableName é LeadboxCRM_AGENTID, então extraímos o sufixo
          const agentSuffix = tableName.replace('LeadboxCRM_', '');
          const messagesTable = `leadbox_messages_${agentSuffix}`;

          try {
            const { error: msgError } = await this.supabase
              .from(messagesTable)
              .update({ remotejid: remotejid })
              .eq('remotejid', oldLidRemoteJid);

            if (msgError) {
              Logger.error(`[Lead Unification] Error updating messages remotejid`, {
                messagesTable,
                oldRemoteJid: oldLidRemoteJid,
                error: msgError
              });
            } else {
              Logger.info(`[Lead Unification] Messages remotejid updated`, {
                messagesTable,
                oldRemoteJid: oldLidRemoteJid,
                newRemoteJid: remotejid
              });
            }
          } catch (msgErr) {
            Logger.error(`[Lead Unification] Exception updating messages`, msgErr);
          }

          return updatedLead;
        }

        // Se o remotejid não era @lid, retornar o lead existente sem modificar
        Logger.debug(`Found existing lead by phone`, {
          tableName,
          leadId: existingByPhone.id,
          remotejid: existingByPhone.remotejid
        });
        return existingByPhone;
      }
    }

    // 3. Se ainda não encontrou, criar novo lead
    return this.createLead(tableName, {
      remotejid,
      pipeline_step: 'Leads',
      status: 'open',
      Atendimento_Finalizado: 'false',
      responsavel: 'AI',
      follow_count: 0,
      ...defaultData,
    });
  }

  // ============================================================================
  // MESSAGES (tabelas leadbox_messages_*)
  // ============================================================================

  async getConversationHistory(tableName: string, remotejid: string): Promise<LeadMessage | null> {
    try {
      Logger.debug(`Getting conversation history from ${tableName} for remotejid: ${remotejid}`);

      const { data, error } = await this.supabase
        .from(tableName)
        .select('*')
        .eq('remotejid', remotejid)
        .order('creat', { ascending: false })
        .limit(1)
        .single();

      if (error) {
        if (error.code === 'PGRST116') {
          Logger.debug(`No conversation history found in ${tableName} for remotejid: ${remotejid}`);
          return null;
        }
        Logger.error(`Error getting conversation history from ${tableName}`, error);
        throw new Error(`Failed to get conversation history: ${error.message}`);
      }

      return data;
    } catch (error) {
      Logger.error(`Exception getting conversation history from ${tableName}`, error);
      throw error;
    }
  }

  /**
   * Upsert conversation history com suporte a timestamps Msg_model/Msg_user
   * @param tableName - Nome da tabela de mensagens
   * @param remotejid - ID do lead
   * @param history - Histórico de conversa (JSONB)
   * @param lastMessageRole - Role da última mensagem ('user' ou 'model') para atualizar timestamp
   */
  async upsertConversationHistory(
    tableName: string,
    remotejid: string,
    history: unknown,
    lastMessageRole?: 'user' | 'model'
  ): Promise<void> {
    try {
      console.log(`[UPSERT HISTORY] Iniciando upsert em ${tableName} para: ${remotejid}`);

      const now = new Date().toISOString();

      // Primeiro, verificar se já existe um registro E buscar o dianaContext existente
      const { data: existingRecord } = await this.supabase
        .from(tableName)
        .select('id, conversation_history')
        .eq('remotejid', remotejid)
        .maybeSingle();

      // IMPORTANTE: Preservar dianaContext se existir (para leads transferidos da Diana)
      const existingHistory = existingRecord?.conversation_history as Record<string, unknown> | undefined;
      const dianaContext = existingHistory?.dianaContext;

      // Merge: preservar dianaContext + atualizar messages
      const newHistory = history as Record<string, unknown>;
      const mergedHistory = dianaContext
        ? { ...newHistory, dianaContext }
        : newHistory;

      if (dianaContext) {
        console.log(`[UPSERT HISTORY] Preservando dianaContext para lead transferido`);
      }

      // Preparar dados de update com timestamps
      const updateData: Record<string, unknown> = {
        conversation_history: mergedHistory,
        creat: now,
      };

      // Atualizar Msg_model ou Msg_user baseado no role da última mensagem
      if (lastMessageRole === 'model') {
        updateData.Msg_model = now;
        console.log(`[UPSERT HISTORY] Atualizando Msg_model = ${now}`);
      } else if (lastMessageRole === 'user') {
        updateData.Msg_user = now;
        console.log(`[UPSERT HISTORY] Atualizando Msg_user = ${now}`);
      }

      let result;

      if (existingRecord) {
        // UPDATE se já existe
        console.log(`[UPSERT HISTORY] Registro existente encontrado, fazendo UPDATE`);
        result = await this.supabase
          .from(tableName)
          .update(updateData)
          .eq('remotejid', remotejid)
          .select();
      } else {
        // INSERT se não existe
        console.log(`[UPSERT HISTORY] Nenhum registro encontrado, fazendo INSERT`);
        result = await this.supabase
          .from(tableName)
          .insert({
            remotejid,
            ...updateData,
          })
          .select();
      }

      if (result.error) {
        console.error(`[UPSERT HISTORY] ERRO em ${tableName}:`, result.error);
        throw new Error(`Failed to upsert conversation history: ${result.error.message}`);
      }

      console.log(`[UPSERT HISTORY] SUCESSO em ${tableName} para: ${remotejid}`, {
        operation: existingRecord ? 'UPDATE' : 'INSERT',
        rowsAffected: result.data?.length || 0,
        lastMessageRole
      });
    } catch (error) {
      Logger.error(`Exception upserting conversation history in ${tableName}`, error);
      throw error;
    }
  }

  /**
   * Atualiza apenas o timestamp de mensagem (Msg_model ou Msg_user)
   * Usado quando precisa atualizar o timestamp sem modificar o histórico
   * Se o registro não existir, cria um novo com o timestamp
   */
  async updateMessageTimestamp(
    tableName: string,
    remotejid: string,
    role: 'user' | 'model'
  ): Promise<void> {
    try {
      const now = new Date().toISOString();
      const updateData: Record<string, string> = {};

      if (role === 'model') {
        updateData.Msg_model = now;
      } else {
        updateData.Msg_user = now;
      }

      console.log(`[UPDATE TIMESTAMP] ${role} timestamp para ${remotejid} = ${now}`);

      // Primeiro tenta atualizar
      const { data: updateResult, error: updateError } = await this.supabase
        .from(tableName)
        .update(updateData)
        .eq('remotejid', remotejid)
        .select('id');

      // Se não atualizou nenhum registro (registro não existe), cria um novo
      if (!updateError && (!updateResult || updateResult.length === 0)) {
        console.log(`[UPDATE TIMESTAMP] Registro não existe, criando novo para ${remotejid}`);
        const insertData: Record<string, unknown> = {
          remotejid,
          creat: now,
          conversation_history: { messages: [] },
          ...updateData,
        };

        const { error: insertError } = await this.supabase
          .from(tableName)
          .insert(insertData);

        if (insertError) {
          // Se falhou insert por constraint unique, o registro foi criado por outra requisição
          if (insertError.code === '23505') {
            console.log(`[UPDATE TIMESTAMP] Registro criado por outra requisição, tentando update novamente`);
            await this.supabase
              .from(tableName)
              .update(updateData)
              .eq('remotejid', remotejid);
          } else {
            Logger.error(`Error inserting new record in ${tableName}`, insertError);
            throw new Error(`Failed to insert timestamp record: ${insertError.message}`);
          }
        }
        Logger.info(`Timestamp ${role} created in ${tableName} for ${remotejid}`);
        return;
      }

      if (updateError) {
        Logger.error(`Error updating ${role} timestamp in ${tableName}`, updateError);
        throw new Error(`Failed to update timestamp: ${updateError.message}`);
      }

      Logger.info(`Timestamp ${role} updated in ${tableName} for ${remotejid}`);
    } catch (error) {
      Logger.error(`Exception updating timestamp in ${tableName}`, error);
      throw error;
    }
  }

  /**
   * Obtém timestamps de mensagem para um lead
   * Usado pelo Salvador para calcular tempo desde última mensagem
   */
  async getMessageTimestamps(
    tableName: string,
    remotejid: string
  ): Promise<{ Msg_model: string | null; Msg_user: string | null } | null> {
    try {
      const { data, error } = await this.supabase
        .from(tableName)
        .select('Msg_model, Msg_user')
        .eq('remotejid', remotejid)
        .single();

      if (error) {
        if (error.code === 'PGRST116') {
          return null;
        }
        throw new Error(`Failed to get timestamps: ${error.message}`);
      }

      return data;
    } catch (error) {
      Logger.error(`Exception getting timestamps from ${tableName}`, error);
      throw error;
    }
  }

  async updateMessage(tableName: string, remotejid: string, data: LeadMessageUpdate): Promise<LeadMessage | null> {
    try {
      Logger.debug(`Updating message in ${tableName} for remotejid: ${remotejid}`, data);

      const { data: message, error } = await this.supabase
        .from(tableName)
        .update(data)
        .eq('remotejid', remotejid)
        .select()
        .single();

      if (error) {
        // PGRST116 = no rows returned (registro não existe)
        if (error.code === 'PGRST116') {
          Logger.debug(`No message found in ${tableName} for remotejid: ${remotejid} - skipping update`);
          return null;
        }
        Logger.error(`Error updating message in ${tableName}`, error);
        throw new Error(`Failed to update message: ${error.message}`);
      }

      Logger.info(`Message updated in ${tableName} for remotejid: ${remotejid}`);
      return message;
    } catch (error) {
      Logger.error(`Exception updating message in ${tableName}`, error);
      throw error;
    }
  }

  async createMessage(tableName: string, data: LeadMessageCreate): Promise<LeadMessage> {
    try {
      Logger.debug(`Creating message in ${tableName}`, data);

      const { data: message, error } = await this.supabase
        .from(tableName)
        .insert(data)
        .select()
        .single();

      if (error) {
        Logger.error(`Error creating message in ${tableName}`, error);
        throw new Error(`Failed to create message: ${error.message}`);
      }

      Logger.info(`Message created in ${tableName}`);
      return message;
    } catch (error) {
      Logger.error(`Exception creating message in ${tableName}`, error);
      throw error;
    }
  }

  // ============================================================================
  // CONTROLE (tabelas Controle_*)
  // ============================================================================

  async findControleByRemoteJid(tableName: string, remotejid: string): Promise<Controle | null> {
    try {
      Logger.debug(`Finding controle in ${tableName} for remotejid: ${remotejid}`);

      const { data, error } = await this.supabase
        .from(tableName)
        .select('*')
        .eq('remotejid', remotejid)
        .single();

      if (error) {
        if (error.code === 'PGRST116') {
          Logger.debug(`No controle found in ${tableName} for remotejid: ${remotejid}`);
          return null;
        }
        Logger.error(`Error finding controle in ${tableName}`, error);
        throw new Error(`Failed to find controle: ${error.message}`);
      }

      return data;
    } catch (error) {
      Logger.error(`Exception finding controle in ${tableName}`, error);
      throw error;
    }
  }

  async createControle(tableName: string, data: ControleCreate): Promise<Controle> {
    try {
      const controleData = {
        ...data,
        created_at: new Date().toISOString(),
      };

      Logger.debug(`Creating controle in ${tableName}`, controleData);

      const { data: controle, error } = await this.supabase
        .from(tableName)
        .insert(controleData)
        .select()
        .single();

      if (error) {
        Logger.error(`Error creating controle in ${tableName}`, error);
        throw new Error(`Failed to create controle: ${error.message}`);
      }

      Logger.info(`Controle created in ${tableName} with id: ${controle.id}`);
      return controle;
    } catch (error) {
      Logger.error(`Exception creating controle in ${tableName}`, error);
      throw error;
    }
  }

  async updateControle(tableName: string, id: number, data: ControleUpdate): Promise<Controle> {
    try {
      const updateData = {
        ...data,
        update_date: new Date().toISOString(),
      };

      Logger.debug(`Updating controle ${id} in ${tableName}`, updateData);

      const { data: controle, error } = await this.supabase
        .from(tableName)
        .update(updateData)
        .eq('id', id)
        .select()
        .single();

      if (error) {
        Logger.error(`Error updating controle in ${tableName}`, error);
        throw new Error(`Failed to update controle: ${error.message}`);
      }

      Logger.info(`Controle ${id} updated in ${tableName}`);
      return controle;
    } catch (error) {
      Logger.error(`Exception updating controle in ${tableName}`, error);
      throw error;
    }
  }

  async updateControleByRemoteJid(tableName: string, remotejid: string, data: ControleUpdate): Promise<Controle> {
    try {
      const updateData = {
        ...data,
        update_date: new Date().toISOString(),
      };

      Logger.debug(`Updating controle by remotejid ${remotejid} in ${tableName}`, updateData);

      const { data: controle, error } = await this.supabase
        .from(tableName)
        .update(updateData)
        .eq('remotejid', remotejid)
        .select()
        .single();

      if (error) {
        Logger.error(`Error updating controle by remotejid in ${tableName}`, error);
        throw new Error(`Failed to update controle: ${error.message}`);
      }

      Logger.info(`Controle updated by remotejid ${remotejid} in ${tableName}`);
      return controle;
    } catch (error) {
      Logger.error(`Exception updating controle by remotejid in ${tableName}`, error);
      throw error;
    }
  }

  async getOrCreateControle(tableName: string, remotejid: string, defaultData?: ControleCreate): Promise<Controle> {
    const existing = await this.findControleByRemoteJid(tableName, remotejid);
    if (existing) {
      return existing;
    }

    return this.createControle(tableName, {
      remotejid,
      ...defaultData,
    });
  }

  // ============================================================================
  // RAW SQL EXECUTION
  // ============================================================================

  async executeRawSQL<T = unknown>(sql: string): Promise<{ data: T | null; error: Error | null }> {
    try {
      Logger.info(`Executing raw SQL query`);
      Logger.debug(`SQL: ${sql}`);

      const { data, error } = await this.supabase.rpc('exec_sql', { query: sql });

      if (error) {
        Logger.error(`Error executing raw SQL`, { error, sql });
        return { data: null, error: new Error(`Failed to execute SQL: ${error.message}`) };
      }

      Logger.info(`Raw SQL executed successfully`);
      Logger.debug(`Result:`, data);

      return { data: data as T, error: null };
    } catch (error) {
      Logger.error(`Exception executing raw SQL`, { error, sql });
      return {
        data: null,
        error: error instanceof Error ? error : new Error('Unknown error executing SQL')
      };
    }
  }

  // ============================================================================
  // HISTORY RESET METHODS (for /123r command)
  // ============================================================================

  /**
   * Deleta o historico de conversa de um lead (tabela leadbox_messages_*)
   * Mantem o registro mas limpa o conversation_history
   *
   * @param tableName - Nome da tabela de mensagens (ex: leadbox_messages_xxx)
   * @param remotejid - ID WhatsApp do lead
   * @returns Numero de registros afetados
   */
  async deleteConversationHistory(tableName: string, remotejid: string): Promise<number> {
    try {
      Logger.info(`Deleting conversation history in ${tableName} for remotejid: ${remotejid}`);

      // Atualizar o conversation_history para vazio ao inves de deletar o registro
      const { data, error } = await this.supabase
        .from(tableName)
        .update({
          conversation_history: { messages: [] },
          Msg_model: null,
          Msg_user: null,
          creat: new Date().toISOString(),
        })
        .eq('remotejid', remotejid)
        .select('id');

      if (error) {
        Logger.error(`Error deleting conversation history in ${tableName}`, error);
        throw new Error(`Failed to delete conversation history: ${error.message}`);
      }

      const count = data?.length || 0;
      Logger.info(`Conversation history cleared in ${tableName}`, { remotejid, recordsAffected: count });
      return count;
    } catch (error) {
      Logger.error(`Exception deleting conversation history in ${tableName}`, error);
      throw error;
    }
  }

  /**
   * Reseta campos do lead para valores iniciais sem deletar o registro
   * Util para o comando /123r que limpa historico mas mantem o lead
   *
   * @param tableName - Nome da tabela de leads (ex: LeadboxCRM_xxx)
   * @param remotejid - ID WhatsApp do lead
   * @returns Lead atualizado ou null se nao encontrado
   */
  async resetLead(tableName: string, remotejid: string): Promise<DynamicLead | null> {
    try {
      Logger.info(`Resetting lead in ${tableName} for remotejid: ${remotejid}`);

      const now = new Date().toISOString();

      // Resetar campos mas manter dados basicos do lead
      const { data: lead, error } = await this.supabase
        .from(tableName)
        .update({
          // Resetar status e pipeline
          pipeline_step: 'Leads',
          status: 'open',
          Atendimento_Finalizado: 'false',
          responsavel: 'AI',
          // Resetar contadores
          follow_count: 0,
          // Resetar qualificacao
          bant_score: null,
          fit_score: null,
          bant_details: null,
          fit_details: null,
          qualification_summary: null,
          // Resetar engagement
          engagement_score: null,
          engagement_level: null,
          // Limpar campos de handoff/takeover
          handed_off_at: null,
          resumed_at: null,
          handoff_reason: null,
          // Atualizar timestamp
          updated_date: now,
        })
        .eq('remotejid', remotejid)
        .select()
        .single();

      if (error) {
        if (error.code === 'PGRST116') {
          Logger.debug(`No lead found in ${tableName} for remotejid: ${remotejid}`);
          return null;
        }
        Logger.error(`Error resetting lead in ${tableName}`, error);
        throw new Error(`Failed to reset lead: ${error.message}`);
      }

      Logger.info(`Lead reset in ${tableName}`, { remotejid, leadId: lead?.id });
      return lead;
    } catch (error) {
      Logger.error(`Exception resetting lead in ${tableName}`, error);
      throw error;
    }
  }
}

// Instancia padrao usando supabaseAdmin
export const dynamicRepository = new DynamicRepository();
