import { SupabaseClient } from '@supabase/supabase-js';
import { supabaseAdmin } from '../client';
import { Agent, AgentCreate, AgentUpdate } from '../types';

const TABLE = 'agents';

export class AgentsRepository {
  private supabase: SupabaseClient;

  constructor(supabase?: SupabaseClient) {
    this.supabase = supabase || supabaseAdmin;
  }

  async findById(id: string): Promise<Agent | null> {
    const { data, error } = await this.supabase
      .from(TABLE)
      .select('*')
      .eq('id', id)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      console.error('[AgentsRepository] Error finding agent by id:', error);
      throw new Error(`Failed to find agent: ${error.message}`);
    }

    return data;
  }

  async findByUserId(userId: string): Promise<Agent[]> {
    const { data, error } = await this.supabase
      .from(TABLE)
      .select('*')
      .eq('user_id', userId)
      .order('created_at', { ascending: false });

    if (error) {
      console.error('[AgentsRepository] Error finding agents by user_id:', error);
      throw new Error(`Failed to find agents: ${error.message}`);
    }

    return data || [];
  }

  /**
   * Busca agent por UAZAPI instance ID
   */
  async findByInstanceId(instanceId: string): Promise<Agent | null> {
    const result = await this.supabase
      .from(TABLE)
      .select('*')
      .eq('uazapi_instance_id', instanceId)
      .single();

    if (result.error) {
      if (result.error.code === 'PGRST116') {
        return null;
      }
      console.error('[AgentsRepository] Error finding agent by instance:', result.error);
      throw new Error(`Failed to find agent: ${result.error.message}`);
    }

    return result.data;
  }

  /**
   * Busca agent por UAZAPI instance ID (exclui sub-agents Salvador)
   */
  async findByUazapiInstancePrimary(instanceId: string): Promise<Agent | null> {
    // Busca agent principal (não tipo 'salvador' que é sub-agent de follow-up)
    // Se houver múltiplos agents com mesmo instance_id, pega o que NÃO é salvador
    const { data, error } = await this.supabase
      .from(TABLE)
      .select('*')
      .eq('uazapi_instance_id', instanceId)
      .neq('type', 'salvador')  // Excluir sub-agents Salvador
      .limit(1)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      // Se ainda houver múltiplos, tentar sem o filtro mas pegar só o primeiro
      if (error.code === 'PGRST204') {
        console.warn('[AgentsRepository] Multiple agents with same instance_id, getting first non-salvador');
        const { data: firstAgent } = await this.supabase
          .from(TABLE)
          .select('*')
          .eq('uazapi_instance_id', instanceId)
          .neq('type', 'salvador')
          .limit(1);
        return firstAgent?.[0] || null;
      }
      console.error('[AgentsRepository] Error finding agent by uazapi instance:', error);
      throw new Error(`Failed to find agent: ${error.message}`);
    }

    return data;
  }

  /**
   * @deprecated Use findByInstanceId instead
   * Busca agent por UAZAPI instance ID ou instance name
   * Busca primeiro por uazapi_instance_id, depois por uazapi_instance_name
   */
  async findByUazapiInstance(instanceId: string): Promise<Agent | null> {
    // Busca por uazapi_instance_id primeiro
    const result = await this.supabase
      .from(TABLE)
      .select('*')
      .eq('uazapi_instance_id', instanceId)
      .single();

    if (!result.error && result.data) {
      return result.data;
    }

    // Se não encontrou por instance_id, buscar por instance_name
    // UAZAPI pode enviar o nome da instância (ex: Agent_18ae1d45) ao invés do ID interno
    const nameResult = await this.supabase
      .from(TABLE)
      .select('*')
      .eq('uazapi_instance_name', instanceId)
      .single();

    if (!nameResult.error && nameResult.data) {
      return nameResult.data;
    }

    // Se não encontrou por nenhum dos dois, retorna null
    if (result.error?.code === 'PGRST116' || nameResult.error?.code === 'PGRST116') {
      return null;
    }

    // Log apenas se for erro diferente de "not found"
    if (result.error?.code !== '42703' && nameResult.error?.code !== '42703') {
      console.error('[AgentsRepository] Error finding agent by uazapi instance:', result.error || nameResult.error);
    }
    return null;
  }

  /**
   * Busca agent por UAZAPI token
   */
  async findByUazapiToken(token: string): Promise<Agent | null> {
    const { data, error } = await this.supabase
      .from(TABLE)
      .select('*')
      .eq('uazapi_token', token)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      console.error('[AgentsRepository] Error finding agent by uazapi token:', error);
      return null;
    }

    return data;
  }

  /**
   * Busca agent por Evolution instance name
   */
  async findByEvolutionInstance(instanceName: string): Promise<Agent | null> {
    const { data, error } = await this.supabase
      .from(TABLE)
      .select('*')
      .eq('evolution_instance_name', instanceName)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      // Ignorar erro de coluna não existe (42703) - tabela pode não ter a coluna ainda
      if (error.code !== '42703') {
        console.error('[AgentsRepository] Error finding agent by evolution instance:', error);
      }
      return null;
    }

    return data;
  }

  async create(data: AgentCreate): Promise<Agent> {
    const { data: agent, error } = await this.supabase
      .from(TABLE)
      .insert(data)
      .select()
      .single();

    if (error) {
      console.error('[AgentsRepository] Error creating agent:', error);
      throw new Error(`Failed to create agent: ${error.message}`);
    }

    return agent;
  }

  async update(id: string, data: AgentUpdate): Promise<Agent> {
    const { data: agent, error } = await this.supabase
      .from(TABLE)
      .update({ ...data, updated_at: new Date().toISOString() })
      .eq('id', id)
      .select()
      .single();

    if (error) {
      console.error('[AgentsRepository] Error updating agent:', error);
      throw new Error(`Failed to update agent: ${error.message}`);
    }

    return agent;
  }

  async delete(id: string): Promise<void> {
    const { error } = await this.supabase
      .from(TABLE)
      .delete()
      .eq('id', id);

    if (error) {
      console.error('[AgentsRepository] Error deleting agent:', error);
      throw new Error(`Failed to delete agent: ${error.message}`);
    }
  }

  /**
   * Atualiza status de conexao UAZAPI
   */
  async updateConnectionStatus(id: string, connected: boolean): Promise<Agent> {
    return this.update(id, { uazapi_connected: connected });
  }

  async findActiveAgents(): Promise<Agent[]> {
    const { data, error } = await this.supabase
      .from(TABLE)
      .select('*')
      .eq('status', 'active')
      .order('created_at', { ascending: false });

    if (error) {
      console.error('[AgentsRepository] Error finding active agents:', error);
      throw new Error(`Failed to find active agents: ${error.message}`);
    }

    return data || [];
  }

  /**
   * Busca o parent agent (Agnes SDR) de um agente Salvador
   * Usado para handoff quando lead reengaja após follow-up
   */
  async findParentAgent(agentId: string): Promise<Agent | null> {
    const agent = await this.findById(agentId);
    if (!agent || !agent.parent_agent_id) {
      return null;
    }

    return this.findById(agent.parent_agent_id);
  }

  /**
   * Busca agentes Salvador (filhos) de um agent Agnes SDR
   */
  async findChildAgents(parentAgentId: string): Promise<Agent[]> {
    const { data, error } = await this.supabase
      .from(TABLE)
      .select('*')
      .eq('parent_agent_id', parentAgentId)
      .eq('status', 'active');

    if (error) {
      console.error('[AgentsRepository] Error finding child agents:', error);
      return [];
    }

    return data || [];
  }

  /**
   * Busca o agente principal (SDR/Agnes) para uma instância UAZAPI
   * Prioriza agentes tipo 'agnes' sobre 'salvador'
   * Retorna também o Salvador se existir para verificação de handoff
   */
  async findAgentsForInstance(instanceId: string): Promise<{
    primaryAgent: Agent | null;
    salvadorAgent: Agent | null;
  }> {
    const { data, error } = await this.supabase
      .from(TABLE)
      .select('*')
      .eq('uazapi_instance_id', instanceId)
      .eq('status', 'active');

    if (error || !data || data.length === 0) {
      return { primaryAgent: null, salvadorAgent: null };
    }

    // Separar agentes por tipo
    const agnesAgent = data.find(a => (a as any).type === 'agnes' || (a as any).agent_type === 'SDR');
    const salvadorAgent = data.find(a => (a as any).type === 'salvador' || (a as any).agent_type === 'FOLLOWUP');

    // Se tem Salvador, verificar parent_agent_id
    if (salvadorAgent && !agnesAgent) {
      // Buscar parent se Salvador existe mas Agnes não está na mesma instância
      const parent = await this.findParentAgent(salvadorAgent.id);
      return {
        primaryAgent: parent,
        salvadorAgent: salvadorAgent,
      };
    }

    return {
      primaryAgent: agnesAgent || data[0],
      salvadorAgent: salvadorAgent || null,
    };
  }
}

// Instancia padrao usando supabaseAdmin
export const agentsRepository = new AgentsRepository();
