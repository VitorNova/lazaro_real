import { FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
import { randomUUID } from 'crypto';

// ============================================================================
// TYPES
// ============================================================================

interface MediaItem {
  id: string;
  type: 'audio' | 'image' | 'video';
  identifier: string; // audio_1, imagem_2, video_1, etc.
  name: string;
  url: string;
  size: number;
  mime_type: string;
  created_at: string;
}

interface UploadMediaBody {
  file_data: string; // Base64 encoded file
  file_name: string;
  file_type: string; // MIME type
  media_type: 'audio' | 'image' | 'video';
}

interface UploadMediaRequest {
  Params: { agentId: string };
  Body: UploadMediaBody;
}

interface DeleteMediaRequest {
  Params: { agentId: string; mediaId: string };
}

interface ListMediasRequest {
  Params: { agentId: string };
}

// ============================================================================
// HELPERS
// ============================================================================

const Logger = {
  info: (msg: string, data?: unknown) => console.info(`[MediaHandler] ${msg}`, data ?? ''),
  warn: (msg: string, data?: unknown) => console.warn(`[MediaHandler] ${msg}`, data ?? ''),
  error: (msg: string, data?: unknown) => console.error(`[MediaHandler] ${msg}`, data ?? ''),
};

/**
 * Gera o identificador sequencial baseado no tipo de midia (formato objeto)
 * Ex: audio_1, audio_2, imagem_1, video_1
 */
function generateIdentifierFromObject(existingMedias: Record<string, any>, type: 'audio' | 'image' | 'video'): string {
  const typePrefix = type === 'audio' ? 'audio' : type === 'image' ? 'imagem' : 'video';

  // Encontrar todas as chaves do mesmo tipo
  const sameTypeKeys = Object.keys(existingMedias).filter(key => key.startsWith(typePrefix + '_'));

  // Extrair numeros usados
  const usedNumbers = sameTypeKeys
    .map(key => {
      const match = key.match(/_(\d+)$/);
      return match ? parseInt(match[1], 10) : 0;
    })
    .sort((a, b) => a - b);

  // Encontrar proximo numero disponivel
  let nextNumber = 1;
  for (const num of usedNumbers) {
    if (num === nextNumber) {
      nextNumber++;
    } else {
      break;
    }
  }

  return `${typePrefix}_${nextNumber}`;
}

/**
 * Converte base64 para Buffer
 */
function base64ToBuffer(base64: string): Buffer {
  // Remove data URL prefix se existir (ex: data:audio/mp3;base64,)
  const base64Data = base64.includes(',') ? base64.split(',')[1] : base64;
  return Buffer.from(base64Data, 'base64');
}

// ============================================================================
// HANDLERS
// ============================================================================

/**
 * POST /api/agents/:agentId/media/upload
 * Upload de midia (audio, imagem, video) para o agente
 */
export async function uploadMediaHandler(
  request: FastifyRequest<UploadMediaRequest>,
  reply: FastifyReply
): Promise<FastifyReply> {
  try {
    const { agentId } = request.params;
    const { file_data, file_name, file_type, media_type } = request.body;
    const userId = (request as any).user?.id || request.headers['x-user-id'];

    if (!userId) {
      return reply.status(401).send({ status: 'error', message: 'Unauthorized' });
    }

    // Validar campos obrigatorios
    if (!file_data || !file_name || !file_type || !media_type) {
      return reply.status(400).send({
        status: 'error',
        message: 'Campos obrigatorios: file_data, file_name, file_type, media_type',
      });
    }

    // Validar tipo de midia
    if (!['audio', 'image', 'video'].includes(media_type)) {
      return reply.status(400).send({
        status: 'error',
        message: 'media_type deve ser: audio, image ou video',
      });
    }

    // Verificar se agente pertence ao usuario
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, name, type, medias')
      .eq('id', agentId)
      .eq('user_id', userId)
      .single();

    if (agentError || !agent) {
      return reply.status(404).send({ status: 'error', message: 'Agent not found' });
    }

    // Verificar se e um agente que suporta midias (Agnes, Diana ou Salvador)
    const allowedTypes = ['agnes', 'diana', 'salvador'];
    if (!allowedTypes.includes(agent.type)) {
      return reply.status(400).send({
        status: 'error',
        message: 'Upload de midia so e permitido para agentes Agnes, Diana ou Salvador',
      });
    }

    Logger.info('Uploading media for agent', { agentId, media_type, file_name });

    // Converter base64 para buffer
    const fileBuffer = base64ToBuffer(file_data);
    const fileSize = fileBuffer.length;

    // Limitar tamanho do arquivo (50MB)
    const maxSize = 50 * 1024 * 1024;
    if (fileSize > maxSize) {
      return reply.status(400).send({
        status: 'error',
        message: 'Arquivo muito grande. Tamanho maximo: 50MB',
      });
    }

    // Gerar identificador unico para o arquivo
    const mediaId = randomUUID();
    const fileExtension = file_name.split('.').pop() || 'bin';
    const storagePath = `agents/${agentId}/media/${mediaId}.${fileExtension}`;

    // Upload para Supabase Storage
    const { data: uploadData, error: uploadError } = await supabaseAdmin.storage
      .from('agent-media')
      .upload(storagePath, fileBuffer, {
        contentType: file_type,
        upsert: false,
      });

    if (uploadError) {
      Logger.error('Failed to upload to storage', { error: uploadError.message });

      // Se o bucket nao existe, criar
      if (uploadError.message.includes('bucket') || uploadError.message.includes('not found')) {
        // Tentar criar o bucket
        const { error: bucketError } = await supabaseAdmin.storage.createBucket('agent-media', {
          public: true,
          fileSizeLimit: 52428800, // 50MB
        });

        if (bucketError && !bucketError.message.includes('already exists')) {
          Logger.error('Failed to create bucket', { error: bucketError.message });
          return reply.status(500).send({
            status: 'error',
            message: 'Erro ao configurar armazenamento',
          });
        }

        // Tentar upload novamente
        const { error: retryError } = await supabaseAdmin.storage
          .from('agent-media')
          .upload(storagePath, fileBuffer, {
            contentType: file_type,
            upsert: false,
          });

        if (retryError) {
          Logger.error('Failed to upload after creating bucket', { error: retryError.message });
          return reply.status(500).send({
            status: 'error',
            message: 'Erro ao fazer upload do arquivo',
          });
        }
      } else {
        return reply.status(500).send({
          status: 'error',
          message: 'Erro ao fazer upload do arquivo',
        });
      }
    }

    // Obter URL publica
    const { data: publicUrlData } = supabaseAdmin.storage
      .from('agent-media')
      .getPublicUrl(storagePath);

    const publicUrl = publicUrlData.publicUrl;

    // Obter midias existentes (formato objeto)
    const existingMedias: Record<string, any> = agent.medias || {};

    // Gerar identificador sequencial baseado nas chaves existentes
    const identifier = generateIdentifierFromObject(existingMedias, media_type);

    // Criar novo item de midia
    const newMedia = {
      id: mediaId,
      type: media_type,
      name: file_name,
      url: publicUrl,
      size: fileSize,
      mime_type: file_type,
      description: '',
      created_at: new Date().toISOString(),
    };

    // Adicionar ao objeto de midias
    const updatedMedias = {
      ...existingMedias,
      [identifier]: newMedia,
    };

    // Atualizar agente com nova midia
    const { error: updateError } = await supabaseAdmin
      .from('agents')
      .update({ medias: updatedMedias })
      .eq('id', agentId);

    if (updateError) {
      Logger.error('Failed to update agent with media', { error: updateError.message });

      // Tentar remover arquivo do storage
      await supabaseAdmin.storage.from('agent-media').remove([storagePath]);

      return reply.status(500).send({
        status: 'error',
        message: 'Erro ao salvar midia no agente',
      });
    }

    Logger.info('Media uploaded successfully', { mediaId, identifier });

    return reply.status(201).send({
      status: 'success',
      message: 'Midia enviada com sucesso',
      media: {
        ...newMedia,
        identifier,
      },
    });

  } catch (error) {
    Logger.error('Unexpected error in uploadMediaHandler', {
      error: error instanceof Error ? error.message : error,
    });
    return reply.status(500).send({
      status: 'error',
      message: 'Erro interno ao processar upload',
    });
  }
}

/**
 * GET /api/agents/:agentId/media
 * Lista todas as midias do agente
 */
export async function listMediasHandler(
  request: FastifyRequest<ListMediasRequest>,
  reply: FastifyReply
): Promise<FastifyReply> {
  try {
    const { agentId } = request.params;
    const userId = (request as any).user?.id || request.headers['x-user-id'];

    if (!userId) {
      return reply.status(401).send({ status: 'error', message: 'Unauthorized' });
    }

    // Verificar se agente pertence ao usuario
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, medias')
      .eq('id', agentId)
      .eq('user_id', userId)
      .single();

    if (agentError || !agent) {
      return reply.status(404).send({ status: 'error', message: 'Agent not found' });
    }

    const mediasObj: Record<string, any> = agent.medias || {};

    // Converter objeto para array com identifier
    const mediasArray = Object.entries(mediasObj).map(([key, value]) => ({
      identifier: key,
      ...value,
    }));

    // Separar por tipo
    const audios = mediasArray.filter(m => m.type === 'audio');
    const images = mediasArray.filter(m => m.type === 'image');
    const videos = mediasArray.filter(m => m.type === 'video');

    return reply.send({
      status: 'success',
      medias: mediasArray,
      mediasObject: mediasObj, // Formato objeto para uso direto
      summary: {
        total: mediasArray.length,
        audios: audios.length,
        images: images.length,
        videos: videos.length,
      },
    });

  } catch (error) {
    Logger.error('Unexpected error in listMediasHandler', {
      error: error instanceof Error ? error.message : error,
    });
    return reply.status(500).send({
      status: 'error',
      message: 'Erro interno ao listar midias',
    });
  }
}

/**
 * DELETE /api/agents/:agentId/media/:mediaId
 * Remove uma midia do agente
 */
export async function deleteMediaHandler(
  request: FastifyRequest<DeleteMediaRequest>,
  reply: FastifyReply
): Promise<FastifyReply> {
  try {
    const { agentId, mediaId } = request.params;
    const userId = (request as any).user?.id || request.headers['x-user-id'];

    if (!userId) {
      return reply.status(401).send({ status: 'error', message: 'Unauthorized' });
    }

    // Verificar se agente pertence ao usuario
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, medias')
      .eq('id', agentId)
      .eq('user_id', userId)
      .single();

    if (agentError || !agent) {
      return reply.status(404).send({ status: 'error', message: 'Agent not found' });
    }

    const mediasObj: Record<string, any> = agent.medias || {};

    // Buscar por ID ou por identifier (chave)
    let identifierToDelete: string | null = null;
    let mediaToDelete: any = null;

    // Primeiro tenta encontrar pelo ID
    for (const [key, value] of Object.entries(mediasObj)) {
      if (value.id === mediaId || key === mediaId) {
        identifierToDelete = key;
        mediaToDelete = value;
        break;
      }
    }

    if (!mediaToDelete) {
      return reply.status(404).send({ status: 'error', message: 'Media not found' });
    }

    Logger.info('Deleting media', { agentId, mediaId, identifier: identifierToDelete });

    // Extrair path do storage da URL
    const urlParts = mediaToDelete.url.split('/agent-media/');
    if (urlParts.length > 1) {
      const storagePath = urlParts[1];

      // Remover do storage
      const { error: deleteStorageError } = await supabaseAdmin.storage
        .from('agent-media')
        .remove([storagePath]);

      if (deleteStorageError) {
        Logger.warn('Failed to delete from storage (continuing anyway)', {
          error: deleteStorageError.message,
        });
      }
    }

    // Remover do objeto
    const { [identifierToDelete!]: removed, ...updatedMedias } = mediasObj;

    // Recalcular identificadores para manter sequencia
    const recalculatedMedias = recalculateIdentifiersObject(updatedMedias);

    const { error: updateError } = await supabaseAdmin
      .from('agents')
      .update({ medias: recalculatedMedias })
      .eq('id', agentId);

    if (updateError) {
      Logger.error('Failed to update agent after media deletion', { error: updateError.message });
      return reply.status(500).send({
        status: 'error',
        message: 'Erro ao atualizar agente',
      });
    }

    Logger.info('Media deleted successfully', { mediaId });

    return reply.send({
      status: 'success',
      message: 'Midia removida com sucesso',
      medias: recalculatedMedias,
    });

  } catch (error) {
    Logger.error('Unexpected error in deleteMediaHandler', {
      error: error instanceof Error ? error.message : error,
    });
    return reply.status(500).send({
      status: 'error',
      message: 'Erro interno ao remover midia',
    });
  }
}

/**
 * Recalcula os identificadores das midias para manter sequencia correta (formato objeto)
 * Apos deletar audio_2, audio_3 vira audio_2
 */
function recalculateIdentifiersObject(medias: Record<string, any>): Record<string, any> {
  const result: Record<string, any> = {};
  const audioCount = { current: 0 };
  const imageCount = { current: 0 };
  const videoCount = { current: 0 };

  // Ordenar por tipo e depois por numero original
  const entries = Object.entries(medias).sort((a, b) => {
    const aNum = parseInt(a[0].match(/_(\d+)$/)?.[1] || '0', 10);
    const bNum = parseInt(b[0].match(/_(\d+)$/)?.[1] || '0', 10);
    return aNum - bNum;
  });

  for (const [oldKey, value] of entries) {
    let newIdentifier: string;

    switch (value.type) {
      case 'audio':
        audioCount.current++;
        newIdentifier = `audio_${audioCount.current}`;
        break;
      case 'image':
        imageCount.current++;
        newIdentifier = `imagem_${imageCount.current}`;
        break;
      case 'video':
        videoCount.current++;
        newIdentifier = `video_${videoCount.current}`;
        break;
      default:
        newIdentifier = oldKey;
    }

    result[newIdentifier] = value;
  }

  return result;
}

// ============================================================================
// AVATAR UPLOAD HANDLERS
// ============================================================================

interface UploadAvatarBody {
  file_data: string; // Base64 encoded file
  file_name: string;
  file_type: string; // MIME type (image/png, image/jpeg, etc.)
}

interface UploadAvatarRequest {
  Params: { agentId: string };
  Body: UploadAvatarBody;
}

interface DeleteAvatarRequest {
  Params: { agentId: string };
}

/**
 * POST /api/agents/:agentId/avatar
 * Upload de foto de perfil do agente
 */
export async function uploadAvatarHandler(
  request: FastifyRequest<UploadAvatarRequest>,
  reply: FastifyReply
): Promise<FastifyReply> {
  try {
    const { agentId } = request.params;
    const { file_data, file_name, file_type } = request.body;
    const userId = (request as any).user?.id || request.headers['x-user-id'];

    if (!userId) {
      return reply.status(401).send({ status: 'error', message: 'Unauthorized' });
    }

    // Validar campos obrigatorios
    if (!file_data || !file_name || !file_type) {
      return reply.status(400).send({
        status: 'error',
        message: 'Campos obrigatorios: file_data, file_name, file_type',
      });
    }

    // Validar tipo de imagem
    const allowedTypes = ['image/png', 'image/jpeg', 'image/jpg', 'image/gif', 'image/webp'];
    if (!allowedTypes.includes(file_type.toLowerCase())) {
      return reply.status(400).send({
        status: 'error',
        message: 'Tipo de arquivo nao permitido. Use: PNG, JPEG, GIF ou WebP',
      });
    }

    // Verificar se agente pertence ao usuario
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, name, avatar_url')
      .eq('id', agentId)
      .eq('user_id', userId)
      .single();

    if (agentError || !agent) {
      return reply.status(404).send({ status: 'error', message: 'Agent not found' });
    }

    Logger.info('Uploading avatar for agent', { agentId, file_name });

    // Converter base64 para buffer
    const fileBuffer = base64ToBuffer(file_data);
    const fileSize = fileBuffer.length;

    // Limitar tamanho do arquivo (5MB para avatares)
    const maxSize = 5 * 1024 * 1024;
    if (fileSize > maxSize) {
      return reply.status(400).send({
        status: 'error',
        message: 'Arquivo muito grande. Tamanho maximo: 5MB',
      });
    }

    // Gerar nome unico para o arquivo
    const fileExtension = file_name.split('.').pop() || 'png';
    const timestamp = Date.now();
    const storagePath = `agents/${agentId}/avatar_${timestamp}.${fileExtension}`;

    // Se ja existe um avatar, remover o antigo
    if (agent.avatar_url) {
      try {
        const oldUrlParts = agent.avatar_url.split('/agent-avatars/');
        if (oldUrlParts.length > 1) {
          const oldPath = oldUrlParts[1];
          await supabaseAdmin.storage.from('agent-avatars').remove([oldPath]);
          Logger.info('Old avatar removed', { oldPath });
        }
      } catch (e) {
        Logger.warn('Failed to remove old avatar (continuing anyway)', { error: e });
      }
    }

    // Upload para Supabase Storage
    const { data: uploadData, error: uploadError } = await supabaseAdmin.storage
      .from('agent-avatars')
      .upload(storagePath, fileBuffer, {
        contentType: file_type,
        upsert: true,
      });

    if (uploadError) {
      Logger.error('Failed to upload avatar to storage', { error: uploadError.message });

      // Se o bucket nao existe, criar
      if (uploadError.message.includes('bucket') || uploadError.message.includes('not found')) {
        // Tentar criar o bucket
        const { error: bucketError } = await supabaseAdmin.storage.createBucket('agent-avatars', {
          public: true,
          fileSizeLimit: 5242880, // 5MB
        });

        if (bucketError && !bucketError.message.includes('already exists')) {
          Logger.error('Failed to create avatar bucket', { error: bucketError.message });
          return reply.status(500).send({
            status: 'error',
            message: 'Erro ao configurar armazenamento de avatares',
          });
        }

        // Tentar upload novamente
        const { error: retryError } = await supabaseAdmin.storage
          .from('agent-avatars')
          .upload(storagePath, fileBuffer, {
            contentType: file_type,
            upsert: true,
          });

        if (retryError) {
          Logger.error('Failed to upload avatar after creating bucket', { error: retryError.message });
          return reply.status(500).send({
            status: 'error',
            message: 'Erro ao fazer upload do avatar',
          });
        }
      } else {
        return reply.status(500).send({
          status: 'error',
          message: 'Erro ao fazer upload do avatar',
        });
      }
    }

    // Obter URL publica
    const { data: publicUrlData } = supabaseAdmin.storage
      .from('agent-avatars')
      .getPublicUrl(storagePath);

    const avatarUrl = publicUrlData.publicUrl;

    // Atualizar agente com nova URL do avatar
    const { error: updateError } = await supabaseAdmin
      .from('agents')
      .update({ avatar_url: avatarUrl })
      .eq('id', agentId);

    if (updateError) {
      Logger.error('Failed to update agent with avatar URL', { error: updateError.message });

      // Tentar remover arquivo do storage
      await supabaseAdmin.storage.from('agent-avatars').remove([storagePath]);

      return reply.status(500).send({
        status: 'error',
        message: 'Erro ao salvar avatar no agente',
      });
    }

    Logger.info('Avatar uploaded successfully', { agentId, avatarUrl });

    return reply.status(200).send({
      status: 'success',
      message: 'Avatar atualizado com sucesso',
      avatar_url: avatarUrl,
    });

  } catch (error) {
    Logger.error('Unexpected error in uploadAvatarHandler', {
      error: error instanceof Error ? error.message : error,
    });
    return reply.status(500).send({
      status: 'error',
      message: 'Erro interno ao processar upload do avatar',
    });
  }
}

/**
 * DELETE /api/agents/:agentId/avatar
 * Remove a foto de perfil do agente
 */
export async function deleteAvatarHandler(
  request: FastifyRequest<DeleteAvatarRequest>,
  reply: FastifyReply
): Promise<FastifyReply> {
  try {
    const { agentId } = request.params;
    const userId = (request as any).user?.id || request.headers['x-user-id'];

    if (!userId) {
      return reply.status(401).send({ status: 'error', message: 'Unauthorized' });
    }

    // Verificar se agente pertence ao usuario
    const { data: agent, error: agentError } = await supabaseAdmin
      .from('agents')
      .select('id, avatar_url')
      .eq('id', agentId)
      .eq('user_id', userId)
      .single();

    if (agentError || !agent) {
      return reply.status(404).send({ status: 'error', message: 'Agent not found' });
    }

    if (!agent.avatar_url) {
      return reply.status(400).send({
        status: 'error',
        message: 'Agente nao possui avatar para remover',
      });
    }

    Logger.info('Deleting avatar for agent', { agentId });

    // Extrair path do storage da URL
    const urlParts = agent.avatar_url.split('/agent-avatars/');
    if (urlParts.length > 1) {
      const storagePath = urlParts[1];

      // Remover do storage
      const { error: deleteStorageError } = await supabaseAdmin.storage
        .from('agent-avatars')
        .remove([storagePath]);

      if (deleteStorageError) {
        Logger.warn('Failed to delete avatar from storage (continuing anyway)', {
          error: deleteStorageError.message,
        });
      }
    }

    // Atualizar agente removendo URL do avatar
    const { error: updateError } = await supabaseAdmin
      .from('agents')
      .update({ avatar_url: null })
      .eq('id', agentId);

    if (updateError) {
      Logger.error('Failed to update agent after avatar deletion', { error: updateError.message });
      return reply.status(500).send({
        status: 'error',
        message: 'Erro ao atualizar agente',
      });
    }

    Logger.info('Avatar deleted successfully', { agentId });

    return reply.send({
      status: 'success',
      message: 'Avatar removido com sucesso',
    });

  } catch (error) {
    Logger.error('Unexpected error in deleteAvatarHandler', {
      error: error instanceof Error ? error.message : error,
    });
    return reply.status(500).send({
      status: 'error',
      message: 'Erro interno ao remover avatar',
    });
  }
}
