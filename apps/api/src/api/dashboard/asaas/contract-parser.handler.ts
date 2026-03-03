import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../../services/supabase/client';
import { AsaasClient } from '../../../services/asaas/client';
import { GoogleGenerativeAI } from '@google/generative-ai';

/**
 * POST /api/dashboard/asaas/parse-contract/:subscriptionId
 *
 * Downloads PDF from Asaas payment documents, extracts text,
 * sends to Gemini for structured data extraction, saves to contract_details.
 */
export async function parseContractHandler(
  request: FastifyRequest,
  reply: FastifyReply
) {
  try {
    const user_id = (request as any).user?.id;
    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    const { subscriptionId } = request.params as { subscriptionId: string };
    if (!subscriptionId) {
      return reply.status(400).send({ status: 'error', message: 'subscriptionId required' });
    }

    // Find the subscription in cache and get the agent's API key
    const { data: contrato } = await supabaseAdmin
      .from('asaas_contratos')
      .select('id, agent_id, customer_id, customer_name')
      .eq('id', subscriptionId)
      .single();

    if (!contrato) {
      return reply.status(404).send({ status: 'error', message: 'Subscription not found' });
    }

    // Verify user owns this agent
    const { data: agent } = await supabaseAdmin
      .from('agents')
      .select('id, asaas_api_key')
      .eq('id', contrato.agent_id)
      .eq('user_id', user_id)
      .not('asaas_api_key', 'is', null)
      .single();

    if (!agent) {
      return reply.status(403).send({ status: 'error', message: 'Unauthorized' });
    }

    const geminiApiKey = process.env.GEMINI_API_KEY;
    if (!geminiApiKey) {
      return reply.status(500).send({ status: 'error', message: 'GEMINI_API_KEY not configured' });
    }

    const asaasClient = new AsaasClient({ apiKey: agent.asaas_api_key });

    // Get payments for this subscription
    // Delay antes da chamada para evitar burst
    await new Promise(resolve => setTimeout(resolve, 200));
    const payments = await asaasClient.listAllPayments({ subscription: subscriptionId, limit: 50 });

    if (!payments || payments.length === 0) {
      return reply.status(404).send({ status: 'error', message: 'No payments found for this subscription' });
    }

    // Collect ALL PDFs from all payments
    const pdfParse = require('pdf-parse');

    interface PdfInfo {
      paymentId: string;
      docId: string;
      docName: string;
      docUrl: string;
    }
    const allPdfInfos: PdfInfo[] = [];
    const allContractData: any[] = [];

    for (const payment of payments) {
      // Delay de 200ms entre cada chamada à API Asaas para evitar rate limiting
      await new Promise(resolve => setTimeout(resolve, 200));
      const docs = await asaasClient.listPaymentDocuments(payment.id);
      const pdfDocs = docs.filter((d: any) => d.name?.toLowerCase().endsWith('.pdf'));

      for (const pdfDoc of pdfDocs) {
        const url = pdfDoc.file?.publicAccessUrl || pdfDoc.file?.downloadUrl;
        if (!url) continue;

        try {
          const buffer = await asaasClient.downloadDocument(url);
          const pdfData = await pdfParse(buffer);
          const pdfText = pdfData.text;

          if (!pdfText || pdfText.trim().length < 50) {
            console.warn(`[ParseContract] PDF ${pdfDoc.name} has no readable text, skipping`);
            continue;
          }

          const extracted = await extractWithGemini(pdfText, geminiApiKey);
          allContractData.push(extracted);
          allPdfInfos.push({
            paymentId: payment.id,
            docId: pdfDoc.id,
            docName: pdfDoc.name,
            docUrl: url,
          });
          console.log(`[ParseContract] Parsed PDF: ${pdfDoc.name} (${extracted.equipamentos?.length || 0} equipamentos)`);
        } catch (err) {
          console.warn(`[ParseContract] Failed to parse ${pdfDoc.name}:`, err);
        }
      }
    }

    if (allPdfInfos.length === 0) {
      return reply.send({
        status: 'success',
        message: 'No PDF documents found for this contract',
        data: null,
      });
    }

    // Merge data from all PDFs
    const contractData = mergeContractData(allContractData);

    // Use first PDF info for reference, store all doc IDs
    const foundPaymentId = allPdfInfos[0].paymentId;
    const foundDocId = allPdfInfos.map(p => p.docId).join(',');
    const foundDocName = allPdfInfos.map(p => p.docName).join(', ');
    const foundDocUrl = allPdfInfos[0].docUrl;

    // Compute derived fields
    const equipamentos = contractData.equipamentos || [];
    const qtdArs = equipamentos.length;
    const valorComercialTotal = equipamentos.reduce(
      (sum: number, eq: any) => sum + (eq.valor_comercial || 0), 0
    );

    console.log(`[ParseContract] Merged ${allPdfInfos.length} PDFs: ${qtdArs} equipamentos, R$ ${valorComercialTotal} valor comercial total`);

    let proximaManutencao: string | null = null;
    if (contractData.data_inicio) {
      const inicio = new Date(contractData.data_inicio);
      inicio.setMonth(inicio.getMonth() + 6);
      proximaManutencao = inicio.toISOString().split('T')[0];
    }

    // Upsert to contract_details
    const record = {
      agent_id: contrato.agent_id,
      subscription_id: subscriptionId,
      customer_id: contrato.customer_id,
      payment_id: foundPaymentId,
      document_id: foundDocId,
      numero_contrato: contractData.numero_contrato || null,
      locatario_nome: contractData.locatario_nome || contrato.customer_name,
      locatario_cpf_cnpj: contractData.locatario_cpf_cnpj || null,
      locatario_telefone: contractData.locatario_telefone || null,
      locatario_endereco: contractData.locatario_endereco || null,
      fiador_nome: contractData.fiador_nome || null,
      fiador_cpf: contractData.fiador_cpf || null,
      fiador_telefone: contractData.fiador_telefone || null,
      equipamentos,
      qtd_ars: qtdArs,
      valor_comercial_total: valorComercialTotal,
      endereco_instalacao: contractData.endereco_instalacao || null,
      prazo_meses: contractData.prazo_meses || null,
      data_inicio: contractData.data_inicio || null,
      data_termino: contractData.data_termino || null,
      dia_vencimento: contractData.dia_vencimento || null,
      valor_mensal: contractData.valor_mensal || null,
      proxima_manutencao: proximaManutencao,
      pdf_url: foundDocUrl,
      pdf_filename: foundDocName,
      parsed_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    const { error } = await supabaseAdmin
      .from('contract_details')
      .upsert(record, { onConflict: 'subscription_id,agent_id' });

    if (error) {
      console.error('[ParseContract] Upsert error:', error);
      return reply.status(500).send({ status: 'error', message: 'Failed to save contract details' });
    }

    return reply.send({
      status: 'success',
      message: `Contract ${contractData.numero_contrato || subscriptionId} parsed successfully (${allPdfInfos.length} PDFs, ${qtdArs} equipamentos)`,
      data: record,
    });
  } catch (error) {
    console.error('[ParseContract] Error:', error);
    return reply.status(500).send({
      status: 'error',
      message: error instanceof Error ? error.message : 'Internal server error',
    });
  }
}

/**
 * POST /api/dashboard/asaas/parse-all-contracts
 *
 * Processes all contracts that haven't been parsed yet.
 * Downloads PDFs from Asaas, extracts data with Gemini, saves to contract_details.
 */
export async function parseAllContractsHandler(
  request: FastifyRequest,
  reply: FastifyReply
) {
  try {
    const user_id = (request as any).user?.id;
    if (!user_id) {
      return reply.status(400).send({ status: 'error', message: 'Authentication required' });
    }

    // Get agentId from query params or find the user's agent with Asaas
    const queryAgentId = (request.query as any)?.agentId;

    let agent: any;

    if (queryAgentId) {
      const { data } = await supabaseAdmin
        .from('agents')
        .select('id, asaas_api_key')
        .eq('id', queryAgentId)
        .eq('user_id', user_id)
        .not('asaas_api_key', 'is', null)
        .single();
      agent = data;
    } else {
      const { data: agents } = await supabaseAdmin
        .from('agents')
        .select('id, asaas_api_key')
        .eq('user_id', user_id)
        .not('asaas_api_key', 'is', null)
        .limit(1);
      agent = agents?.[0];
    }

    if (!agent) {
      return reply.status(404).send({ status: 'error', message: 'No Asaas integration found' });
    }

    const geminiApiKey = process.env.GEMINI_API_KEY;
    if (!geminiApiKey) {
      return reply.status(500).send({ status: 'error', message: 'GEMINI_API_KEY not configured' });
    }

    // Check if force re-parse is requested
    const forceReparse = (request.query as any)?.force === 'true';

    // Get all contracts that haven't been parsed yet
    const { data: allContracts } = await supabaseAdmin
      .from('asaas_contratos')
      .select('id, customer_id, customer_name')
      .eq('agent_id', agent.id)
      .eq('status', 'ACTIVE');

    const { data: parsedContracts } = await supabaseAdmin
      .from('contract_details')
      .select('subscription_id')
      .eq('agent_id', agent.id);

    const parsedIds = new Set(parsedContracts?.map(c => c.subscription_id) || []);

    // If force=true, process ALL contracts; otherwise only pending ones
    const pendingContracts = forceReparse
      ? (allContracts || [])
      : (allContracts?.filter(c => !parsedIds.has(c.id)) || []);

    console.log(`[ParseAllContracts] Found ${pendingContracts.length} contracts to parse (force=${forceReparse})`);

    if (pendingContracts.length === 0) {
      return reply.send({
        status: 'success',
        message: 'All contracts already parsed',
        data: { total: allContracts?.length || 0, parsed: parsedIds.size, pending: 0 },
      });
    }

    const asaasClient = new AsaasClient({ apiKey: agent.asaas_api_key });
    const pdfParse = require('pdf-parse');

    const results: { success: string[]; failed: string[]; skipped: string[] } = {
      success: [],
      failed: [],
      skipped: [],
    };

    const startTime = Date.now();
    let totalRequests = 0;

    // Process each contract
    for (const contrato of pendingContracts) {
      try {
        console.log(`[ParseAllContracts] Processing ${contrato.id} (${contrato.customer_name})`);

        // Get payments for this subscription
        // Delay antes da chamada para evitar burst
        await new Promise(resolve => setTimeout(resolve, 200));
        totalRequests++;
        const payments = await asaasClient.listAllPayments({ subscription: contrato.id, limit: 50 });

        if (!payments || payments.length === 0) {
          console.log(`[ParseAllContracts] No payments for ${contrato.id}, skipping`);
          results.skipped.push(`${contrato.id} (no payments)`);
          continue;
        }

        console.log(`[ParseAllContracts] Found ${payments.length} payments for ${contrato.id}`);

        // Collect PDFs from all payments
        interface PdfInfo {
          paymentId: string;
          docId: string;
          docName: string;
          docUrl: string;
        }
        const allPdfInfos: PdfInfo[] = [];
        const allContractData: any[] = [];

        for (const payment of payments) {
          // Delay de 200ms entre cada chamada à API Asaas para evitar rate limiting
          await new Promise(resolve => setTimeout(resolve, 200));
          totalRequests++;
          const docs = await asaasClient.listPaymentDocuments(payment.id);
          const pdfDocs = docs.filter((d: any) => d.name?.toLowerCase().endsWith('.pdf'));

          for (const pdfDoc of pdfDocs) {
            const url = pdfDoc.file?.publicAccessUrl || pdfDoc.file?.downloadUrl;
            if (!url) continue;

            try {
              const buffer = await asaasClient.downloadDocument(url);
              const pdfData = await pdfParse(buffer);
              const pdfText = pdfData.text;

              if (!pdfText || pdfText.trim().length < 50) {
                console.warn(`[ParseAllContracts] PDF ${pdfDoc.name} has no readable text, skipping`);
                continue;
              }

              const extracted = await extractWithGemini(pdfText, geminiApiKey);
              allContractData.push(extracted);
              allPdfInfos.push({
                paymentId: payment.id,
                docId: pdfDoc.id,
                docName: pdfDoc.name,
                docUrl: url,
              });

              // Rate limit: wait 500ms between Gemini calls
              await new Promise(resolve => setTimeout(resolve, 500));
            } catch (err) {
              console.warn(`[ParseAllContracts] Failed to parse ${pdfDoc.name}:`, err);
            }
          }
        }

        if (allPdfInfos.length === 0) {
          console.log(`[ParseAllContracts] No PDFs found for ${contrato.id}, skipping`);
          results.skipped.push(`${contrato.id} (no PDFs)`);
          continue;
        }

        // Merge data from all PDFs
        const contractData = mergeContractData(allContractData);

        const foundPaymentId = allPdfInfos[0].paymentId;
        const foundDocId = allPdfInfos.map(p => p.docId).join(',');
        const foundDocName = allPdfInfos.map(p => p.docName).join(', ');
        const foundDocUrl = allPdfInfos[0].docUrl;

        const equipamentos = contractData.equipamentos || [];
        const qtdArs = equipamentos.length;
        const valorComercialTotal = equipamentos.reduce(
          (sum: number, eq: any) => sum + (eq.valor_comercial || 0), 0
        );

        let proximaManutencao: string | null = null;
        if (contractData.data_inicio) {
          const inicio = new Date(contractData.data_inicio);
          inicio.setMonth(inicio.getMonth() + 6);
          proximaManutencao = inicio.toISOString().split('T')[0];
        }

        // Upsert to contract_details
        const record = {
          agent_id: agent.id,
          subscription_id: contrato.id,
          customer_id: contrato.customer_id,
          payment_id: foundPaymentId,
          document_id: foundDocId,
          numero_contrato: contractData.numero_contrato || null,
          locatario_nome: contractData.locatario_nome || contrato.customer_name,
          locatario_cpf_cnpj: contractData.locatario_cpf_cnpj || null,
          locatario_telefone: contractData.locatario_telefone || null,
          locatario_endereco: contractData.locatario_endereco || null,
          fiador_nome: contractData.fiador_nome || null,
          fiador_cpf: contractData.fiador_cpf || null,
          fiador_telefone: contractData.fiador_telefone || null,
          equipamentos,
          qtd_ars: qtdArs,
          valor_comercial_total: valorComercialTotal,
          endereco_instalacao: contractData.endereco_instalacao || null,
          prazo_meses: contractData.prazo_meses || null,
          data_inicio: contractData.data_inicio || null,
          data_termino: contractData.data_termino || null,
          dia_vencimento: contractData.dia_vencimento || null,
          valor_mensal: contractData.valor_mensal || null,
          proxima_manutencao: proximaManutencao,
          pdf_url: foundDocUrl,
          pdf_filename: foundDocName,
          parsed_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };

        const { error } = await supabaseAdmin
          .from('contract_details')
          .upsert(record, { onConflict: 'subscription_id,agent_id' });

        if (error) {
          console.error(`[ParseAllContracts] Upsert error for ${contrato.id}:`, error);
          results.failed.push(`${contrato.id} (db error)`);
        } else {
          console.log(`[ParseAllContracts] ✓ Parsed ${contrato.id}: ${qtdArs} equipamentos`);
          results.success.push(`${contrato.id} (${qtdArs} equip.)`);
        }

        // Rate limit between contracts
        await new Promise(resolve => setTimeout(resolve, 1000));

      } catch (err) {
        console.error(`[ParseAllContracts] Error processing ${contrato.id}:`, err);
        results.failed.push(`${contrato.id} (${err instanceof Error ? err.message : 'error'})`);
      }
    }

    const elapsedTime = ((Date.now() - startTime) / 1000).toFixed(1);
    const avgTimePerContract = pendingContracts.length > 0
      ? (parseFloat(elapsedTime) / pendingContracts.length).toFixed(1)
      : '0';

    console.log(`[ParseAllContracts] Concluído em ${elapsedTime}s | ${totalRequests} requisições à API Asaas | Média: ${avgTimePerContract}s/contrato`);

    return reply.send({
      status: 'success',
      message: `Processed ${results.success.length} contracts`,
      data: {
        total: allContracts?.length || 0,
        alreadyParsed: parsedIds.size,
        processed: results.success.length,
        failed: results.failed.length,
        skipped: results.skipped.length,
        details: results,
        stats: {
          elapsedSeconds: parseFloat(elapsedTime),
          totalAsaasRequests: totalRequests,
          avgSecondsPerContract: parseFloat(avgTimePerContract),
        },
      },
    });

  } catch (error) {
    console.error('[ParseAllContracts] Error:', error);
    return reply.status(500).send({
      status: 'error',
      message: error instanceof Error ? error.message : 'Internal server error',
    });
  }
}

/**
 * Merges contract data extracted from multiple PDFs into a single record.
 * Scalar fields: takes first non-null value found.
 * Equipamentos: merges all arrays into one.
 */
export function mergeContractData(dataList: any[]): any {
  if (dataList.length === 0) return {};
  if (dataList.length === 1) return dataList[0];

  const result: any = {};
  const scalarFields = [
    'numero_contrato', 'locatario_nome', 'locatario_cpf_cnpj',
    'locatario_telefone', 'locatario_endereco', 'fiador_nome',
    'fiador_cpf', 'fiador_telefone', 'endereco_instalacao',
    'prazo_meses', 'data_inicio', 'data_termino',
    'dia_vencimento', 'valor_mensal',
  ];

  for (const field of scalarFields) {
    for (const data of dataList) {
      if (data[field] != null) {
        result[field] = data[field];
        break;
      }
    }
  }

  // Merge all equipment arrays from all PDFs
  const allEquipamentos: any[] = [];
  for (const data of dataList) {
    if (data.equipamentos && Array.isArray(data.equipamentos)) {
      allEquipamentos.push(...data.equipamentos);
    }
  }
  result.equipamentos = allEquipamentos;

  return result;
}

/**
 * Sends extracted PDF text to Gemini and gets structured JSON back
 */
export async function extractWithGemini(pdfText: string, apiKey: string): Promise<any> {
  const genAI = new GoogleGenerativeAI(apiKey);
  const model = genAI.getGenerativeModel({ model: 'gemini-2.0-flash' });

  const prompt = `Analise o texto de um contrato de locação de ar-condicionado da ALUGA AR e extraia os dados em JSON.

=== NUMERAÇÃO DE CONTRATOS ===

O número do contrato segue o formato "N-X" (ex: "131-2"), onde:
- N = número sequencial do CLIENTE (identifica o cliente de forma única)
- X = número do contrato ou aditivo daquele cliente

Exemplos:
- "Contrato 131-1" → Cliente nº 131, primeiro contrato
- "Contrato 131-2" → Cliente nº 131, segundo contrato (aditivo)
- "Contrato 45-3" → Cliente nº 45, terceiro contrato

O campo "numero_contrato" deve conter o número completo (ex: "131-2").
O campo "numero_cliente" deve conter apenas o número antes do hífen (ex: 131).
O campo "numero_aditivo" deve conter apenas o número depois do hífen (ex: 2).

Procure por padrões como:
- "CONTRATO DE LOCAÇÃO DE BEM MÓVEL Nº 131-2"
- "ADITIVO AO CONTRATO DE LOCAÇÃO DE BEM MÓVEL Nº 131-2"
- "contrato nº 131-2"
- "contrato nº 131 -2" (pode ter espaço antes do hífen)

=== REGRA DE CONTAGEM DE CLIENTES ===

- O número antes do hífen (N) identifica o cliente de forma ÚNICA
- Contratos 131-1, 131-2 e 131-3 = 1 CLIENTE (nº 131) com 3 contratos
- Para contar total de clientes, conte quantos números N diferentes existem
- Exemplo: contratos 45-1, 45-2, 131-1, 131-2, 200-1 = 3 clientes (45, 131, 200)

=== TIPO DE DOCUMENTO ===

Identifique se é:
- "contrato" → Contrato original (geralmente N-1)
- "aditivo" → Aditivo ao contrato (N-2, N-3, etc.) — pode ser substituição de equipamento, alteração de valor, renovação

Pistas para identificar ADITIVO:
- Título contém "ADITIVO"
- Menciona "substituição do equipamento"
- Referencia um contrato original anterior
- Menciona "Termo de Substituição e Vistoria"

=== TIPOS DE TABELA DE EQUIPAMENTOS ===

TIPO 1: Tabela com coluna "item" (descrição)
Colunas: codigo | item (descrição) | Valor Locacao | Valor Comercial
Exemplo: "000307  PATRIMONIO 0540 - AR CONDICIONADO VG 12.000 BTUS INVERTER   189,00   2.700,00"
- O código "000307" NÃO é o patrimônio
- Extraia "0540" do texto "PATRIMONIO 0540" na descrição
- BTUS: Extraia da descrição do item (ex: "12.000 BTUS" → 12000)
- Cada linha = 1 equipamento

TIPO 2: Tabela com coluna "MARCA" contendo patrimônios
Colunas: MARCA | MODELO | BTUS | VALOR COMERCIAL
Exemplo: "SPRINGER MIDEA, Patrimônios 0329/ 0330/ 0331/ 0332 0333/ 0334  |  CONVENCIONAL  |  9.000 CADA  |  R$2.500,00"
- A marca é "SPRINGER MIDEA"
- Os patrimônios estão após "Patrimônios" separados por "/" ou espaço: 0329, 0330, 0331, 0332, 0333, 0334
- BTUS: Extraia da coluna BTUS (ex: "9.000 CADA" → 9000)
- CADA patrimônio = 1 equipamento separado no JSON
- Se há 11 patrimônios, gere 11 objetos no array "equipamentos"

TIPO 3: Tabela de aditivo (substituição)
Colunas: ITEM | Valor Locação | Valor Comercial
Exemplo: "PATRIMONIO 0345-AR CONDICIONADO FONTAINE 9.000BTUS127VOLTS   R$ 149,00   2.500,00"
- Patrimônio: "0345"
- Marca: "FONTAINE"
- BTUs: 9000
- Voltagem: 127V
- Em aditivos, verifique também o equipamento ANTERIOR que está sendo substituído (ex: "PATRIMONIO 133-AR CONDICIONADO BRITANIA 12.000BTUS 220V")

=== REGRAS DE PATRIMÔNIO ===

- Patrimônio é sempre um código numérico de 3-4 dígitos (ex: "0540", "0329", "155", "0345")
- Se aparecer "PATRI", "Patrimônio", "Patrimônios" ou "PATRIMONIO", extraia os números que seguem
- Nunca use o "codigo" da primeira coluna como patrimônio
- Em aditivos, extraia TANTO o equipamento novo quanto o antigo (campo "equipamento_substituido")

=== EXTRAÇÃO DE DATAS ===

Procure por:
- "firmado em DD/MM/YYYY" → data_inicio
- "com término em DD/MM/YYYY" ou "com termo em DD/MM/YYYY" → data_termino
- "vigência de DD/MM/YYYY a DD/MM/YYYY"
- "prazo de XX meses a partir de DD/MM/YYYY"
- Data de assinatura no final do documento (ex: "Rondonópolis-MT, 06 de dezembro de 2025")

Em ADITIVOS, a frase típica é:
"conforme previsto no contrato nº 131-2, firmado em 14/10/2025, com termo em 14/10/2026"
→ data_inicio: "2025-10-14", data_termino: "2026-10-14"

Converta DD/MM/YYYY para YYYY-MM-DD:
- 14/10/2025 → "2025-10-14"
- 06/12/2025 → "2025-12-06"

=== EXTRAÇÃO DE DADOS DO LOCATÁRIO ===

- Nome completo
- CPF ou CNPJ (limpe formatação: "062.070.951.03" → "06207095103")
- Telefone (se disponível)
- Endereço completo (rua, número, bairro, cidade, CEP)
- Estado civil, profissão (se disponível)

=== EXTRAÇÃO DE FIADOR ===

Se houver fiador no contrato, extraia nome, CPF e telefone.

=== EXTRAÇÃO DE TESTEMUNHAS ===

Se houver testemunhas, extraia nomes e CPFs.

=== DADOS DA ASSINATURA DIGITAL ===

Se o documento tiver assinatura via Autentique ou similar, extraia:
- Plataforma (ex: "Autentique")
- Hash do documento
- Data/hora de cada assinatura
- IP de cada signatário

Texto do contrato:
---
${pdfText.substring(0, 8000)}
---

Retorne APENAS um JSON válido (sem markdown, sem \`\`\`) com esta estrutura:
{
  "tipo_documento": "contrato | aditivo",
  "numero_contrato": "131-2",
  "numero_cliente": 131,
  "numero_aditivo": 2,
  "locatario_nome": "string",
  "locatario_cpf_cnpj": "string ou null",
  "locatario_telefone": "string ou null",
  "locatario_endereco": "string ou null",
  "locatario_estado_civil": "string ou null",
  "locatario_profissao": "string ou null",
  "fiador_nome": "string ou null",
  "fiador_cpf": "string ou null",
  "fiador_telefone": "string ou null",
  "equipamentos": [
    {
      "patrimonio": "0345",
      "marca": "FONTAINE",
      "modelo": "string ou null",
      "btus": 9000,
      "voltagem": "127V ou null",
      "valor_locacao": 149.00,
      "valor_comercial": 2500.00
    }
  ],
  "equipamento_substituido": {
    "patrimonio": "133",
    "marca": "BRITANIA",
    "modelo": "string ou null",
    "btus": 12000,
    "voltagem": "220V ou null"
  },
  "endereco_instalacao": "string ou null",
  "prazo_meses": 12,
  "data_inicio": "2025-10-14",
  "data_termino": "2026-10-14",
  "data_assinatura": "2025-12-06",
  "dia_vencimento": 15,
  "valor_mensal": 149.00,
  "renovacao_automatica": true,
  "aviso_previo_dias": 30,
  "testemunhas": [
    {
      "nome": "TIELI PAULINO DA SILVA PACHECO",
      "cpf": "02101705141"
    }
  ],
  "assinatura_digital": {
    "plataforma": "Autentique",
    "hash": "string ou null",
    "assinaturas": [
      {
        "nome": "string",
        "cpf": "string",
        "data_hora": "2025-12-06T09:53:05",
        "ip": "string"
      }
    ]
  }
}

Se um campo não existir, use null. Se não for aditivo, "equipamento_substituido" = null. Datas em YYYY-MM-DD. Valores em número decimal.`;

  const result = await model.generateContent(prompt);
  const text = result.response.text();
  const cleaned = text.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();

  try {
    return JSON.parse(cleaned);
  } catch {
    console.error('[Gemini] Invalid JSON response:', cleaned.substring(0, 300));
    throw new Error('Gemini returned invalid JSON');
  }
}

/**
 * Helper: Parse a single contract (internal version without reply)
 */
export async function parseContractInternal(
  subscriptionId: string,
  customerId: string,
  customerName: string,
  agentId: string,
  asaasClient: AsaasClient,
  geminiApiKey: string
): Promise<boolean> {
  const pdfParse = require('pdf-parse');

  // Get payments for this subscription
  await new Promise(resolve => setTimeout(resolve, 200));
  const payments = await asaasClient.listAllPayments({ subscription: subscriptionId, limit: 50 });

  if (!payments || payments.length === 0) {
    return false;
  }

  const allPdfInfos: any[] = [];
  const allContractData: any[] = [];

  for (const payment of payments.slice(0, 5)) { // Limit to 5 payments
    await new Promise(resolve => setTimeout(resolve, 200));
    const docs = await asaasClient.listPaymentDocuments(payment.id);
    const pdfDocs = docs.filter((d: any) => d.name?.toLowerCase().endsWith('.pdf'));

    for (const pdfDoc of pdfDocs) {
      const url = pdfDoc.file?.publicAccessUrl || pdfDoc.file?.downloadUrl;
      if (!url) continue;

      try {
        const buffer = await asaasClient.downloadDocument(url);
        const pdfData = await pdfParse(buffer);
        const pdfText = pdfData.text;

        if (!pdfText || pdfText.trim().length < 50) {
          continue;
        }

        const extracted = await extractWithGemini(pdfText, geminiApiKey);
        if (extracted) {
          allContractData.push(extracted);
          allPdfInfos.push({
            paymentId: payment.id,
            docId: pdfDoc.id,
            docName: pdfDoc.name,
            docUrl: url,
          });
        }
        await new Promise(resolve => setTimeout(resolve, 500));
      } catch (err) {
        // Skip failed PDFs
      }
    }
  }

  if (allPdfInfos.length === 0) {
    return false;
  }

  // Merge data from all PDFs
  const contractData = mergeContractData(allContractData);

  const equipamentos = contractData.equipamentos || [];
  const qtdArs = equipamentos.length;
  const valorComercialTotal = equipamentos.reduce(
    (sum: number, eq: any) => sum + (eq.valor_comercial || 0), 0
  );

  let proximaManutencao: string | null = null;
  if (contractData.data_inicio) {
    const inicio = new Date(contractData.data_inicio);
    inicio.setMonth(inicio.getMonth() + 6);
    proximaManutencao = inicio.toISOString().split('T')[0];
  }

  const record = {
    agent_id: agentId,
    subscription_id: subscriptionId,
    customer_id: customerId,
    payment_id: allPdfInfos[0].paymentId,
    document_id: allPdfInfos.map(p => p.docId).join(','),
    // Novos campos de numeração
    tipo_documento: contractData.tipo_documento || null,
    numero_contrato: contractData.numero_contrato || null,
    numero_cliente: contractData.numero_cliente || null,
    numero_aditivo: contractData.numero_aditivo || null,
    // Dados do locatário
    locatario_nome: contractData.locatario_nome || customerName,
    locatario_cpf_cnpj: contractData.locatario_cpf_cnpj || null,
    locatario_telefone: contractData.locatario_telefone || null,
    locatario_endereco: contractData.locatario_endereco || null,
    locatario_estado_civil: contractData.locatario_estado_civil || null,
    locatario_profissao: contractData.locatario_profissao || null,
    // Fiador
    fiador_nome: contractData.fiador_nome || null,
    fiador_cpf: contractData.fiador_cpf || null,
    fiador_telefone: contractData.fiador_telefone || null,
    // Equipamentos
    equipamentos,
    equipamento_substituido: contractData.equipamento_substituido || null,
    qtd_ars: qtdArs,
    valor_comercial_total: valorComercialTotal,
    endereco_instalacao: contractData.endereco_instalacao || null,
    // Datas e prazos
    prazo_meses: contractData.prazo_meses || null,
    data_inicio: contractData.data_inicio || null,
    data_termino: contractData.data_termino || null,
    data_assinatura: contractData.data_assinatura || null,
    dia_vencimento: contractData.dia_vencimento || null,
    valor_mensal: contractData.valor_mensal || null,
    proxima_manutencao: proximaManutencao,
    // Termos do contrato
    renovacao_automatica: contractData.renovacao_automatica ?? null,
    aviso_previo_dias: contractData.aviso_previo_dias || null,
    // Testemunhas e assinatura digital
    testemunhas: contractData.testemunhas || null,
    assinatura_digital: contractData.assinatura_digital || null,
    // Metadados
    pdf_url: allPdfInfos[0].docUrl,
    pdf_filename: allPdfInfos.map(p => p.docName).join(', '),
    parsed_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  const { error } = await supabaseAdmin
    .from('contract_details')
    .upsert(record, { onConflict: 'subscription_id,agent_id' });

  if (error) {
    console.error('[ParseContractInternal] Upsert error:', error);
    return false;
  }

  return true;
}
