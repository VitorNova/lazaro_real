/**
 * User Settings Routes
 *
 * Extracted from index.legacy.ts - Phase 9.11
 *
 * Handles user configuration (logo, company name, etc.)
 */

import { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import { supabaseAdmin } from '../../services/supabase/client';
import { legacyAuthMiddleware, AuthenticatedRequest } from '../middleware/auth.middleware';

/**
 * Auth middleware wrapper for compatibility
 */
async function authMiddleware(
  request: FastifyRequest,
  reply: FastifyReply
): Promise<void> {
  await legacyAuthMiddleware(request, reply);
  const authRequest = request as AuthenticatedRequest;
  if (authRequest.user) {
    (request as unknown as { user: { id: string } }).user = { id: authRequest.user.userId };
  }
}

/**
 * Register user settings routes
 */
export async function registerUserSettingsRoutes(fastify: FastifyInstance): Promise<void> {
  console.info('[UserSettingsRoutes] Registering user settings routes...');

  // GET /api/users/:userId/settings - Obter configurações do usuário
  fastify.get<{ Params: { userId: string } }>(
    '/api/users/:userId/settings',
    { preHandler: authMiddleware },
    async (request, reply) => {
      try {
        const { userId } = request.params;
        const authUserId = (request as any).user?.id;

        console.info('[UserSettings] GET request - userId:', userId, 'authUserId:', authUserId);

        // Verificar se o usuário está acessando suas próprias configurações
        if (userId !== authUserId) {
          console.error('[UserSettings] Access denied - userId:', userId, 'authUserId:', authUserId);
          return reply.status(403).send({ status: 'error', message: 'Access denied' });
        }

        // Buscar configurações do usuário
        const { data: settings, error } = await supabaseAdmin
          .from('user_settings')
          .select('*')
          .eq('user_id', userId)
          .single();

        if (error && error.code !== 'PGRST116') {
          console.error('[UserSettings] Error fetching settings:', error);
          return reply.status(500).send({ status: 'error', message: 'Failed to fetch settings' });
        }

        return reply.send({
          status: 'success',
          settings: settings || {
            logo_url: null,
            company_name: '',
          },
        });
      } catch (error) {
        console.error('[UserSettings] Error:', error);
        return reply.status(500).send({ status: 'error', message: 'Internal server error' });
      }
    }
  );

  // PUT /api/users/:userId/settings - Atualizar configurações do usuário
  fastify.put<{
    Params: { userId: string };
    Body: {
      company_name?: string;
      logo_data?: string | null;
      logo_name?: string | null;
      logo_type?: string | null;
      remove_logo?: boolean;
    };
  }>(
    '/api/users/:userId/settings',
    { preHandler: authMiddleware },
    async (request, reply) => {
      try {
        const { userId } = request.params;
        const { company_name, logo_data, logo_name, logo_type, remove_logo } = request.body;
        const authUserId = (request as any).user?.id;

        console.info('[UserSettings] PUT request - userId:', userId, 'authUserId:', authUserId);

        // Verificar se o usuário está atualizando suas próprias configurações
        if (userId !== authUserId) {
          console.error('[UserSettings] Access denied - userId:', userId, 'authUserId:', authUserId);
          return reply.status(403).send({ status: 'error', message: 'Access denied' });
        }

        let logoUrl: string | null = null;

        // Se deve remover a logo
        if (remove_logo) {
          // Buscar logo atual para deletar do storage
          const { data: currentSettings } = await supabaseAdmin
            .from('user_settings')
            .select('logo_url')
            .eq('user_id', userId)
            .single();

          if (currentSettings?.logo_url) {
            // Extrair path do storage da URL
            const urlParts = currentSettings.logo_url.split('/user-logos/');
            if (urlParts.length > 1) {
              const filePath = urlParts[1];
              await supabaseAdmin.storage.from('user-logos').remove([filePath]);
            }
          }

          logoUrl = null;
        }
        // Se há nova logo para upload
        else if (logo_data && logo_name && logo_type) {
          // Remover logo antiga se existir
          const { data: currentSettings } = await supabaseAdmin
            .from('user_settings')
            .select('logo_url')
            .eq('user_id', userId)
            .single();

          if (currentSettings?.logo_url) {
            const urlParts = currentSettings.logo_url.split('/user-logos/');
            if (urlParts.length > 1) {
              const filePath = urlParts[1];
              await supabaseAdmin.storage.from('user-logos').remove([filePath]);
            }
          }

          // Upload da nova logo
          const base64Data = logo_data.split(',')[1] || logo_data;
          const buffer = Buffer.from(base64Data, 'base64');
          const extension = logo_name.split('.').pop() || 'png';
          const fileName = `${userId}/logo_${Date.now()}.${extension}`;

          const { error: uploadError } = await supabaseAdmin.storage
            .from('user-logos')
            .upload(fileName, buffer, {
              contentType: logo_type,
              upsert: true,
            });

          if (uploadError) {
            console.error('[UserSettings] Error uploading logo:', uploadError);
            return reply.status(500).send({ status: 'error', message: 'Failed to upload logo' });
          }

          // Obter URL pública
          const { data: urlData } = supabaseAdmin.storage
            .from('user-logos')
            .getPublicUrl(fileName);

          logoUrl = urlData.publicUrl;
        }

        // Upsert das configurações
        const updateData: Record<string, any> = {
          user_id: userId,
          updated_at: new Date().toISOString(),
        };

        if (company_name !== undefined) {
          updateData.company_name = company_name;
        }

        if (remove_logo || logo_data) {
          updateData.logo_url = logoUrl;
        }

        const { data: settings, error: upsertError } = await supabaseAdmin
          .from('user_settings')
          .upsert(updateData, { onConflict: 'user_id' })
          .select()
          .single();

        if (upsertError) {
          console.error('[UserSettings] Error upserting settings:', upsertError);
          return reply.status(500).send({ status: 'error', message: 'Failed to save settings' });
        }

        console.info('[UserSettings] Settings updated for user:', userId);

        return reply.send({
          status: 'success',
          message: 'Settings saved successfully',
          settings,
        });
      } catch (error) {
        console.error('[UserSettings] Error:', error);
        return reply.status(500).send({ status: 'error', message: 'Internal server error' });
      }
    }
  );

  console.info('[UserSettingsRoutes] User settings routes registered.');
}
