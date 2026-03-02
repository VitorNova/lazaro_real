import { SupabaseClient } from '@supabase/supabase-js';
import { supabaseAdmin } from '../client';

const TABLE = 'brazil_timezones';

/**
 * Interface para os dados da tabela brazil_timezones
 */
export interface BrazilTimezone {
  id: number;
  state_code: string;
  state_name: string;
  timezone: string;
  timezone_friendly: string;
  utc_offset: string;
  aliases: string[];
  major_cities: string[];
  created_at: string;
  updated_at: string;
}

/**
 * Resultado da detecção de timezone
 */
export interface TimezoneDetectionResult {
  found: boolean;
  timezone: string | null;
  timezone_friendly: string | null;
  state_code: string | null;
  state_name: string | null;
  utc_offset: string | null;
  matched_by: 'state_code' | 'alias' | 'city' | null;
  matched_term: string | null;
}

/**
 * Repository para consultar timezones brasileiros
 *
 * Usa a tabela brazil_timezones que contém:
 * - Todos os 27 estados brasileiros + Fernando de Noronha
 * - Aliases (variações de escrita como "minas", "sampa", etc)
 * - Cidades principais para matching
 */
export class TimezonesRepository {
  private supabase: SupabaseClient;
  private cache: Map<string, TimezoneDetectionResult> = new Map();

  constructor(supabase?: SupabaseClient) {
    this.supabase = supabase || supabaseAdmin;
  }

  /**
   * Detecta timezone baseado em uma string de localização
   *
   * @param location - String informada pelo lead (ex: "minas", "SP", "cuiaba")
   * @returns Resultado da detecção com timezone ou null se não encontrado
   *
   * @example
   * const result = await timezonesRepository.detectTimezone("minas");
   * // { found: true, timezone: "America/Sao_Paulo", state_code: "MG", ... }
   */
  async detectTimezone(location: string): Promise<TimezoneDetectionResult> {
    if (!location || typeof location !== 'string') {
      return this.notFoundResult();
    }

    // Normalizar input
    const normalized = this.normalizeString(location);

    // Verificar cache
    const cached = this.cache.get(normalized);
    if (cached) {
      console.log(`[TimezonesRepository] Cache hit for: ${normalized}`);
      return cached;
    }

    try {
      // 1. Tentar match exato por state_code (UF)
      if (normalized.length === 2) {
        const byCode = await this.findByStateCode(normalized.toUpperCase());
        if (byCode) {
          const result = this.buildResult(byCode, 'state_code', normalized);
          this.cache.set(normalized, result);
          return result;
        }
      }

      // 2. Buscar todos os registros e fazer matching em memória
      // IMPORTANTE: A ordem das verificacoes importa para evitar falsos positivos!
      // Ex: "sao paulo" contem "pa" (Para), entao match parcial daria errado.
      const allStates = await this.getAllStates();

      // ========================================================================
      // FASE 1: MATCH EXATO (prioridade maxima)
      // ========================================================================
      for (const state of allStates) {
        // 1.1 Match EXATO em aliases
        const normalizedAliases = state.aliases.map(a => this.normalizeString(a));
        if (normalizedAliases.includes(normalized)) {
          const matchedAlias = normalizedAliases.find(a => a === normalized)!;
          const result = this.buildResult(state, 'alias', matchedAlias);
          this.cache.set(normalized, result);
          return result;
        }

        // 1.2 Match EXATO em cidades
        const normalizedCities = state.major_cities.map(c => this.normalizeString(c));
        if (normalizedCities.includes(normalized)) {
          const matchedCity = normalizedCities.find(c => c === normalized)!;
          const result = this.buildResult(state, 'city', matchedCity);
          this.cache.set(normalized, result);
          return result;
        }

        // 1.3 Match EXATO no nome do estado
        const normalizedStateName = this.normalizeString(state.state_name);
        if (normalizedStateName === normalized) {
          const result = this.buildResult(state, 'alias', state.state_name);
          this.cache.set(normalized, result);
          return result;
        }
      }

      // ========================================================================
      // FASE 2: MATCH PARCIAL (apenas se input contem o termo, NAO o contrario)
      // Ex: "interior de sp" contem "sp" -> OK
      // Ex: "sao paulo" contem "pa" -> IGNORAR (falso positivo)
      // ========================================================================
      // So fazer match parcial se o termo buscado for MAIOR que o alias/cidade
      // Isso evita que "sao paulo" case com "pa" (Para)
      for (const state of allStates) {
        // 2.1 Match parcial em aliases (input contem alias E alias tem pelo menos 3 chars)
        const normalizedAliases = state.aliases.map(a => this.normalizeString(a));
        for (const alias of normalizedAliases) {
          // So considerar match parcial se:
          // - O alias tiver pelo menos 3 caracteres (evita "pa", "sp", etc)
          // - O input contiver o alias como palavra completa
          if (alias.length >= 3 && this.containsWholeWord(normalized, alias)) {
            const result = this.buildResult(state, 'alias', alias);
            this.cache.set(normalized, result);
            return result;
          }
        }

        // 2.2 Match parcial em cidades
        const normalizedCities = state.major_cities.map(c => this.normalizeString(c));
        for (const city of normalizedCities) {
          if (city.length >= 3 && this.containsWholeWord(normalized, city)) {
            const result = this.buildResult(state, 'city', city);
            this.cache.set(normalized, result);
            return result;
          }
        }

        // 2.3 Match parcial no nome do estado (input contem nome do estado)
        const normalizedStateName = this.normalizeString(state.state_name);
        if (normalizedStateName.length >= 3 && this.containsWholeWord(normalized, normalizedStateName)) {
          const result = this.buildResult(state, 'alias', state.state_name);
          this.cache.set(normalized, result);
          return result;
        }
      }

      // ========================================================================
      // FASE 3: MATCH REVERSO (alias/cidade contem o input, se input for grande)
      // Ex: "rio grande do sul" contem "rio grande" -> OK
      // Mas so se o input tiver pelo menos 5 chars para evitar falsos positivos
      // ========================================================================
      if (normalized.length >= 5) {
        for (const state of allStates) {
          // Nome do estado contem o input
          const normalizedStateName = this.normalizeString(state.state_name);
          if (normalizedStateName.includes(normalized)) {
            const result = this.buildResult(state, 'alias', state.state_name);
            this.cache.set(normalized, result);
            return result;
          }

          // Algum alias contem o input
          const normalizedAliases = state.aliases.map(a => this.normalizeString(a));
          for (const alias of normalizedAliases) {
            if (alias.includes(normalized)) {
              const result = this.buildResult(state, 'alias', alias);
              this.cache.set(normalized, result);
              return result;
            }
          }
        }
      }

      // Não encontrado
      const notFound = this.notFoundResult();
      this.cache.set(normalized, notFound);
      return notFound;

    } catch (error) {
      console.error('[TimezonesRepository] Error detecting timezone:', error);
      return this.notFoundResult();
    }
  }

  /**
   * Busca estado por código (UF)
   */
  async findByStateCode(code: string): Promise<BrazilTimezone | null> {
    const { data, error } = await this.supabase
      .from(TABLE)
      .select('*')
      .eq('state_code', code.toUpperCase())
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      console.error('[TimezonesRepository] Error finding by state_code:', error);
      return null;
    }

    return data;
  }

  /**
   * Busca todos os estados (com cache interno)
   */
  private allStatesCache: BrazilTimezone[] | null = null;
  private allStatesCacheTime: number = 0;
  private readonly CACHE_TTL = 5 * 60 * 1000; // 5 minutos

  async getAllStates(): Promise<BrazilTimezone[]> {
    const now = Date.now();

    // Retornar cache se válido
    if (this.allStatesCache && (now - this.allStatesCacheTime) < this.CACHE_TTL) {
      return this.allStatesCache;
    }

    const { data, error } = await this.supabase
      .from(TABLE)
      .select('*')
      .order('state_code');

    if (error) {
      console.error('[TimezonesRepository] Error fetching all states:', error);
      return this.allStatesCache || [];
    }

    this.allStatesCache = data || [];
    this.allStatesCacheTime = now;
    return this.allStatesCache;
  }

  /**
   * Limpa o cache (útil para testes ou após atualizações)
   */
  clearCache(): void {
    this.cache.clear();
    this.allStatesCache = null;
    this.allStatesCacheTime = 0;
  }

  /**
   * Normaliza string para comparação
   * Remove acentos, converte para minúsculo, remove caracteres especiais
   */
  private normalizeString(str: string): string {
    return str
      .toLowerCase()
      .trim()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '') // Remove acentos
      .replace(/[^\w\s]/g, '') // Remove caracteres especiais
      .replace(/\s+/g, ' '); // Normaliza espaços
  }

  /**
   * Verifica se text contem word como palavra completa (nao como substring)
   *
   * Ex: "interior de sp" contem "sp" como palavra? SIM (separado por espaco)
   * Ex: "sao paulo" contem "pa" como palavra? NAO ("pa" esta dentro de "paulo")
   *
   * @param text - Texto onde buscar
   * @param word - Palavra a buscar
   * @returns true se word aparece como palavra completa em text
   */
  private containsWholeWord(text: string, word: string): boolean {
    // Se word tem espacos, verificar se text contem essa sequencia
    if (word.includes(' ')) {
      return text.includes(word);
    }

    // Para palavras unicas, usar regex de word boundary
    // Adaptado para funcionar com strings normalizadas (sem acentos)
    const words = text.split(/\s+/);
    return words.includes(word);
  }

  /**
   * Constrói resultado de sucesso
   */
  private buildResult(
    state: BrazilTimezone,
    matchedBy: 'state_code' | 'alias' | 'city',
    matchedTerm: string
  ): TimezoneDetectionResult {
    return {
      found: true,
      timezone: state.timezone,
      timezone_friendly: state.timezone_friendly,
      state_code: state.state_code,
      state_name: state.state_name,
      utc_offset: state.utc_offset,
      matched_by: matchedBy,
      matched_term: matchedTerm,
    };
  }

  /**
   * Constrói resultado de não encontrado
   */
  private notFoundResult(): TimezoneDetectionResult {
    return {
      found: false,
      timezone: null,
      timezone_friendly: null,
      state_code: null,
      state_name: null,
      utc_offset: null,
      matched_by: null,
      matched_term: null,
    };
  }
}

// Instância singleton
export const timezonesRepository = new TimezonesRepository();
