import { supabaseAdmin } from '../client';
import {
  Payment,
  PaymentCreate,
  PaymentUpdate,
  PaymentStatus,
} from '../types';

const TABLE = 'payments';

export const paymentsRepository = {
  async create(orgId: string, data: Omit<PaymentCreate, 'organization_id'>): Promise<Payment> {
    const { data: payment, error } = await supabaseAdmin
      .from(TABLE)
      .insert({ ...data, organization_id: orgId })
      .select()
      .single();

    if (error) {
      console.error('[PaymentsRepository] Error creating payment:', error);
      throw new Error(`Failed to create payment: ${error.message}`);
    }

    return payment;
  },

  async getById(orgId: string, id: string): Promise<Payment | null> {
    const { data: payment, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('id', id)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      console.error('[PaymentsRepository] Error getting payment by id:', error);
      throw new Error(`Failed to get payment: ${error.message}`);
    }

    return payment;
  },

  async getByLeadId(orgId: string, leadId: string): Promise<Payment[]> {
    const { data: payments, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('lead_id', leadId)
      .order('created_at', { ascending: false });

    if (error) {
      console.error('[PaymentsRepository] Error getting payments by lead_id:', error);
      throw new Error(`Failed to get payments: ${error.message}`);
    }

    return payments || [];
  },

  async getByRemoteJid(orgId: string, remoteJid: string): Promise<Payment[]> {
    const { data: payments, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('remote_jid', remoteJid)
      .order('created_at', { ascending: false });

    if (error) {
      console.error('[PaymentsRepository] Error getting payments by remote_jid:', error);
      throw new Error(`Failed to get payments: ${error.message}`);
    }

    return payments || [];
  },

  async update(orgId: string, id: string, data: PaymentUpdate): Promise<Payment> {
    const { data: payment, error } = await supabaseAdmin
      .from(TABLE)
      .update(data)
      .eq('organization_id', orgId)
      .eq('id', id)
      .select()
      .single();

    if (error) {
      console.error('[PaymentsRepository] Error updating payment:', error);
      throw new Error(`Failed to update payment: ${error.message}`);
    }

    return payment;
  },

  async markAsPaid(orgId: string, id: string): Promise<Payment> {
    const { data: payment, error } = await supabaseAdmin
      .from(TABLE)
      .update({
        status: PaymentStatus.RECEIVED,
        paid_at: new Date().toISOString(),
      })
      .eq('organization_id', orgId)
      .eq('id', id)
      .select()
      .single();

    if (error) {
      console.error('[PaymentsRepository] Error marking payment as paid:', error);
      throw new Error(`Failed to mark payment as paid: ${error.message}`);
    }

    return payment;
  },

  async updateStatus(orgId: string, id: string, status: PaymentStatus): Promise<Payment> {
    const updateData: PaymentUpdate = { status };

    if (status === PaymentStatus.RECEIVED) {
      updateData.paid_at = new Date().toISOString();
    }

    return this.update(orgId, id, updateData);
  },

  async getByAsaasPaymentLinkId(orgId: string, paymentLinkId: string): Promise<Payment | null> {
    const { data: payment, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('asaas_payment_link_id', paymentLinkId)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      console.error('[PaymentsRepository] Error getting payment by asaas_payment_link_id:', error);
      throw new Error(`Failed to get payment: ${error.message}`);
    }

    return payment;
  },

  async getByAsaasCustomerId(orgId: string, customerId: string): Promise<Payment[]> {
    const { data: payments, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('asaas_customer_id', customerId)
      .order('created_at', { ascending: false });

    if (error) {
      console.error('[PaymentsRepository] Error getting payments by asaas_customer_id:', error);
      throw new Error(`Failed to get payments: ${error.message}`);
    }

    return payments || [];
  },

  async listPending(orgId: string): Promise<Payment[]> {
    const { data: payments, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('status', PaymentStatus.PENDING)
      .order('created_at', { ascending: true });

    if (error) {
      console.error('[PaymentsRepository] Error listing pending payments:', error);
      throw new Error(`Failed to list pending payments: ${error.message}`);
    }

    return payments || [];
  },

  async listOverdue(orgId: string): Promise<Payment[]> {
    const { data: payments, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('status', PaymentStatus.OVERDUE)
      .order('created_at', { ascending: true });

    if (error) {
      console.error('[PaymentsRepository] Error listing overdue payments:', error);
      throw new Error(`Failed to list overdue payments: ${error.message}`);
    }

    return payments || [];
  },

  async delete(orgId: string, id: string): Promise<void> {
    const { error } = await supabaseAdmin
      .from(TABLE)
      .delete()
      .eq('organization_id', orgId)
      .eq('id', id);

    if (error) {
      console.error('[PaymentsRepository] Error deleting payment:', error);
      throw new Error(`Failed to delete payment: ${error.message}`);
    }
  },

  /**
   * Busca pagamento pelo ID do Asaas (asaas_payment_id)
   */
  async getByAsaasId(orgId: string, asaasPaymentId: string): Promise<Payment | null> {
    const { data: payment, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('organization_id', orgId)
      .eq('asaas_payment_id', asaasPaymentId)
      .single();

    if (error) {
      if (error.code === 'PGRST116') {
        return null;
      }
      console.error('[PaymentsRepository] Error getting payment by asaas_id:', error);
      throw new Error(`Failed to get payment: ${error.message}`);
    }

    return payment;
  },

  /**
   * Lista pagamentos de um lead ordenados por data de criação
   */
  async listByLead(leadId: string): Promise<Payment[]> {
    const { data: payments, error } = await supabaseAdmin
      .from(TABLE)
      .select()
      .eq('lead_id', leadId)
      .order('created_at', { ascending: false });

    if (error) {
      console.error('[PaymentsRepository] Error listing payments by lead:', error);
      throw new Error(`Failed to list payments: ${error.message}`);
    }

    return payments || [];
  },
};
