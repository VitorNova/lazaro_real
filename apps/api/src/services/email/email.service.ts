// ============================================================================
// EMAIL SERVICE
// Serviço para envio de emails (verificação, reset de senha, etc)
// ============================================================================

// ============================================================================
// TYPES
// ============================================================================

export interface EmailOptions {
  to: string;
  subject: string;
  html: string;
  text?: string;
}

export interface EmailResult {
  success: boolean;
  messageId?: string;
  error?: string;
}

// ============================================================================
// EMAIL SERVICE CLASS
// ============================================================================

export class EmailService {
  private apiKey: string;
  private fromEmail: string;
  private frontendUrl: string;
  private isConfigured: boolean;

  constructor() {
    this.apiKey = process.env.RESEND_API_KEY || '';
    this.fromEmail = process.env.EMAIL_FROM || 'Agnes Agent <noreply@example.com>';
    this.frontendUrl = process.env.FRONTEND_URL || 'http://localhost:3000';
    this.isConfigured = !!this.apiKey && !this.apiKey.includes('your_');

    if (!this.isConfigured) {
      console.warn('[EmailService] Email não configurado. Emails serão logados no console.');
    }
  }

  // ==========================================================================
  // SEND EMAIL
  // ==========================================================================

  async send(options: EmailOptions): Promise<EmailResult> {
    const { to, subject, html, text } = options;

    // Se não está configurado, apenas logar
    if (!this.isConfigured) {
      console.log('[EmailService] Email simulado:', {
        to,
        subject,
        preview: html.substring(0, 200) + '...',
      });
      return {
        success: true,
        messageId: `simulated-${Date.now()}`,
      };
    }

    try {
      const response = await fetch('https://api.resend.com/emails', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${this.apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          from: this.fromEmail,
          to: [to],
          subject,
          html,
          text: text || this.htmlToText(html),
        }),
      });

      if (!response.ok) {
        const errorData = await response.json() as { message?: string };
        console.error('[EmailService] Erro ao enviar:', errorData);
        return {
          success: false,
          error: errorData.message || 'Erro ao enviar email',
        };
      }

      const data = await response.json() as { id?: string };
      console.log('[EmailService] Email enviado:', { to, subject, id: data.id });

      return {
        success: true,
        messageId: data.id,
      };
    } catch (error) {
      console.error('[EmailService] Exception:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Erro desconhecido',
      };
    }
  }

  // ==========================================================================
  // EMAIL TEMPLATES
  // ==========================================================================

  /**
   * Email de boas-vindas e verificação
   */
  async sendWelcomeEmail(to: string, name: string, verificationToken: string): Promise<EmailResult> {
    const verificationUrl = `${this.frontendUrl}/auth/verify-email?token=${verificationToken}`;

    const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Bem-vindo ao Agnes Agent</title>
</head>
<body style="margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f5f5f5;">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 600px; margin: 0 auto; padding: 20px;">
    <tr>
      <td style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 40px 30px; border-radius: 10px 10px 0 0; text-align: center;">
        <h1 style="color: white; margin: 0; font-size: 28px;">Agnes Agent</h1>
        <p style="color: rgba(255,255,255,0.9); margin: 10px 0 0 0;">Sua plataforma de agentes inteligentes</p>
      </td>
    </tr>
    <tr>
      <td style="background: white; padding: 40px 30px; border-radius: 0 0 10px 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
        <h2 style="color: #333; margin: 0 0 20px 0;">Olá, ${name}!</h2>

        <p style="color: #666; line-height: 1.6; margin: 0 0 20px 0;">
          Seja bem-vindo ao Agnes Agent! Sua conta foi criada com sucesso.
        </p>

        <p style="color: #666; line-height: 1.6; margin: 0 0 30px 0;">
          Para começar a usar a plataforma, confirme seu email clicando no botão abaixo:
        </p>

        <div style="text-align: center; margin: 30px 0;">
          <a href="${verificationUrl}" style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; padding: 15px 40px; border-radius: 8px; font-weight: bold; font-size: 16px;">
            Verificar Email
          </a>
        </div>

        <p style="color: #999; font-size: 14px; line-height: 1.6; margin: 30px 0 0 0;">
          Se o botão não funcionar, copie e cole este link no seu navegador:<br>
          <a href="${verificationUrl}" style="color: #667eea; word-break: break-all;">${verificationUrl}</a>
        </p>

        <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">

        <p style="color: #999; font-size: 12px; text-align: center; margin: 0;">
          Este link expira em 24 horas.<br>
          Se você não criou esta conta, ignore este email.
        </p>
      </td>
    </tr>
  </table>
</body>
</html>
    `;

    return this.send({
      to,
      subject: 'Bem-vindo ao Agnes Agent - Confirme seu email',
      html,
    });
  }

  /**
   * Email de reset de senha
   */
  async sendPasswordResetEmail(to: string, name: string, resetToken: string): Promise<EmailResult> {
    const resetUrl = `${this.frontendUrl}/auth/reset-password?token=${resetToken}`;

    const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Redefinir Senha - Agnes Agent</title>
</head>
<body style="margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f5f5f5;">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 600px; margin: 0 auto; padding: 20px;">
    <tr>
      <td style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 40px 30px; border-radius: 10px 10px 0 0; text-align: center;">
        <h1 style="color: white; margin: 0; font-size: 28px;">Agnes Agent</h1>
        <p style="color: rgba(255,255,255,0.9); margin: 10px 0 0 0;">Redefinição de Senha</p>
      </td>
    </tr>
    <tr>
      <td style="background: white; padding: 40px 30px; border-radius: 0 0 10px 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
        <h2 style="color: #333; margin: 0 0 20px 0;">Olá, ${name}!</h2>

        <p style="color: #666; line-height: 1.6; margin: 0 0 20px 0;">
          Recebemos uma solicitação para redefinir a senha da sua conta.
        </p>

        <p style="color: #666; line-height: 1.6; margin: 0 0 30px 0;">
          Clique no botão abaixo para criar uma nova senha:
        </p>

        <div style="text-align: center; margin: 30px 0;">
          <a href="${resetUrl}" style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; padding: 15px 40px; border-radius: 8px; font-weight: bold; font-size: 16px;">
            Redefinir Senha
          </a>
        </div>

        <p style="color: #999; font-size: 14px; line-height: 1.6; margin: 30px 0 0 0;">
          Se o botão não funcionar, copie e cole este link no seu navegador:<br>
          <a href="${resetUrl}" style="color: #667eea; word-break: break-all;">${resetUrl}</a>
        </p>

        <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">

        <p style="color: #999; font-size: 12px; text-align: center; margin: 0;">
          Este link expira em 1 hora.<br>
          Se você não solicitou esta redefinição, ignore este email. Sua senha não será alterada.
        </p>
      </td>
    </tr>
  </table>
</body>
</html>
    `;

    return this.send({
      to,
      subject: 'Redefinir sua senha - Agnes Agent',
      html,
    });
  }

  /**
   * Email de confirmação de alteração de senha
   */
  async sendPasswordChangedEmail(to: string, name: string): Promise<EmailResult> {
    const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Senha Alterada - Agnes Agent</title>
</head>
<body style="margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f5f5f5;">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 600px; margin: 0 auto; padding: 20px;">
    <tr>
      <td style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 40px 30px; border-radius: 10px 10px 0 0; text-align: center;">
        <h1 style="color: white; margin: 0; font-size: 28px;">Agnes Agent</h1>
        <p style="color: rgba(255,255,255,0.9); margin: 10px 0 0 0;">Notificação de Segurança</p>
      </td>
    </tr>
    <tr>
      <td style="background: white; padding: 40px 30px; border-radius: 0 0 10px 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
        <h2 style="color: #333; margin: 0 0 20px 0;">Olá, ${name}!</h2>

        <p style="color: #666; line-height: 1.6; margin: 0 0 20px 0;">
          Sua senha foi alterada com sucesso.
        </p>

        <p style="color: #666; line-height: 1.6; margin: 0 0 20px 0;">
          Se você fez essa alteração, nenhuma ação é necessária.
        </p>

        <div style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; border-radius: 4px;">
          <p style="color: #856404; margin: 0; font-size: 14px;">
            <strong>Não foi você?</strong><br>
            Entre em contato conosco imediatamente se você não reconhece essa atividade.
          </p>
        </div>

        <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">

        <p style="color: #999; font-size: 12px; text-align: center; margin: 0;">
          Este é um email automático de segurança.<br>
          Agnes Agent - Plataforma de Agentes Inteligentes
        </p>
      </td>
    </tr>
  </table>
</body>
</html>
    `;

    return this.send({
      to,
      subject: 'Sua senha foi alterada - Agnes Agent',
      html,
    });
  }

  // ==========================================================================
  // HELPERS
  // ==========================================================================

  private htmlToText(html: string): string {
    return html
      .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, '')
      .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '')
      .replace(/<[^>]+>/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }
}

// ============================================================================
// SINGLETON INSTANCE
// ============================================================================

let emailServiceInstance: EmailService | null = null;

export function getEmailService(): EmailService {
  if (!emailServiceInstance) {
    emailServiceInstance = new EmailService();
  }
  return emailServiceInstance;
}

export function createEmailService(): EmailService {
  return new EmailService();
}
