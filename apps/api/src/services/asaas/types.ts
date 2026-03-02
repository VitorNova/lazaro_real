// ============================================================================
// CONFIGURAÇÃO
// ============================================================================

export interface AsaasConfig {
  apiKey: string;
  baseUrl?: string; // Opcional - usa ASAAS_BASE_URL se não fornecido
}

export const ASAAS_BASE_URL = 'https://api.asaas.com/v3';

// ============================================================================
// ENUMS
// ============================================================================

export enum BillingType {
  BOLETO = 'BOLETO',
  CREDIT_CARD = 'CREDIT_CARD',
  DEBIT_CARD = 'DEBIT_CARD',
  PIX = 'PIX',
  UNDEFINED = 'UNDEFINED', // Permite cliente escolher
}

export enum Cycle {
  WEEKLY = 'WEEKLY',
  BIWEEKLY = 'BIWEEKLY',
  MONTHLY = 'MONTHLY',
  BIMONTHLY = 'BIMONTHLY',
  QUARTERLY = 'QUARTERLY',
  SEMIANNUALLY = 'SEMIANNUALLY',
  YEARLY = 'YEARLY',
}

export enum ChargeType {
  DETACHED = 'DETACHED', // Cobrança avulsa
  RECURRENT = 'RECURRENT', // Cobrança recorrente
  INSTALLMENT = 'INSTALLMENT', // Parcelamento
}

export enum PaymentStatus {
  PENDING = 'PENDING',
  RECEIVED = 'RECEIVED',
  CONFIRMED = 'CONFIRMED',
  OVERDUE = 'OVERDUE',
  REFUNDED = 'REFUNDED',
  RECEIVED_IN_CASH = 'RECEIVED_IN_CASH',
  REFUND_REQUESTED = 'REFUND_REQUESTED',
  REFUND_IN_PROGRESS = 'REFUND_IN_PROGRESS',
  CHARGEBACK_REQUESTED = 'CHARGEBACK_REQUESTED',
  CHARGEBACK_DISPUTE = 'CHARGEBACK_DISPUTE',
  AWAITING_CHARGEBACK_REVERSAL = 'AWAITING_CHARGEBACK_REVERSAL',
  DUNNING_REQUESTED = 'DUNNING_REQUESTED',
  DUNNING_RECEIVED = 'DUNNING_RECEIVED',
  AWAITING_RISK_ANALYSIS = 'AWAITING_RISK_ANALYSIS',
}

export enum SubscriptionStatus {
  ACTIVE = 'ACTIVE',
  INACTIVE = 'INACTIVE',
  EXPIRED = 'EXPIRED',
}

export enum PaymentLinkStatus {
  ACTIVE = 'ACTIVE',
  INACTIVE = 'INACTIVE',
}

// ============================================================================
// CUSTOMER (CLIENTE)
// ============================================================================

export interface AsaasCustomer {
  id: string;
  name: string;
  email?: string;
  phone?: string;
  mobilePhone?: string;
  cpfCnpj?: string;
  personType?: 'FISICA' | 'JURIDICA';
  postalCode?: string;
  address?: string;
  addressNumber?: string;
  complement?: string;
  province?: string;
  city?: number | null;
  cityName?: string;
  state?: string;
  country?: string;
  company?: string;
  externalReference?: string;
  notificationDisabled?: boolean;
  additionalEmails?: string;
  municipalInscription?: string;
  stateInscription?: string;
  observations?: string;
  groupName?: string;
  foreignCustomer?: boolean;
  dateCreated?: string;
  deleted?: boolean;
  canDelete?: boolean;
  canEdit?: boolean;
}

export interface CreateCustomerInput {
  name: string;
  email?: string;
  phone?: string;
  mobilePhone?: string;
  cpfCnpj?: string;
  postalCode?: string;
  address?: string;
  addressNumber?: string;
  complement?: string;
  province?: string;
  city?: string;
  state?: string;
  externalReference?: string;
  notificationDisabled?: boolean;
  additionalEmails?: string;
  groupName?: string;
}

export interface UpdateCustomerInput {
  name?: string;
  email?: string;
  phone?: string;
  mobilePhone?: string;
  cpfCnpj?: string;
  postalCode?: string;
  address?: string;
  addressNumber?: string;
  complement?: string;
  province?: string;
  city?: string;
  state?: string;
  externalReference?: string;
  notificationDisabled?: boolean;
  additionalEmails?: string;
  groupName?: string;
}

// ============================================================================
// SUBSCRIPTION (ASSINATURA)
// ============================================================================

export interface AsaasSubscription {
  id: string;
  customer: string;
  billingType: BillingType;
  value: number;
  nextDueDate: string;
  cycle: Cycle;
  description?: string;
  endDate?: string;
  maxPayments?: number;
  status: SubscriptionStatus;
  externalReference?: string;
  dateCreated: string;
  deleted?: boolean;
}

export interface CreateSubscriptionInput {
  customer: string; // Customer ID
  billingType: BillingType;
  value: number;
  nextDueDate: string; // YYYY-MM-DD
  cycle: Cycle;
  description?: string;
  endDate?: string; // YYYY-MM-DD
  maxPayments?: number;
  externalReference?: string;
  // Configurações de desconto
  discount?: {
    value: number;
    dueDateLimitDays?: number;
    type?: 'FIXED' | 'PERCENTAGE';
  };
  // Configurações de multa e juros
  fine?: {
    value: number;
    type?: 'FIXED' | 'PERCENTAGE';
  };
  interest?: {
    value: number; // Percentual ao mês
  };
}

export interface UpdateSubscriptionInput {
  billingType?: BillingType;
  value?: number;
  nextDueDate?: string;
  cycle?: Cycle;
  description?: string;
  endDate?: string;
  maxPayments?: number;
  externalReference?: string;
  discount?: {
    value: number;
    dueDateLimitDays?: number;
    type?: 'FIXED' | 'PERCENTAGE';
  };
}

// ============================================================================
// PAYMENT LINK (LINK DE PAGAMENTO)
// ============================================================================

export interface AsaasPaymentLink {
  id: string;
  name: string;
  url: string;
  value?: number;
  description?: string;
  billingType: BillingType;
  chargeType: ChargeType;
  subscriptionCycle?: Cycle;
  maxInstallmentCount?: number;
  dueDateLimitDays?: number;
  active: boolean;
  dateCreated: string;
  deleted?: boolean;
  externalReference?: string;
  notificationEnabled?: boolean;
}

export interface CreatePaymentLinkInput {
  name: string;
  description?: string;
  value?: number; // Opcional para links de valor aberto
  billingType: BillingType;
  chargeType: ChargeType;
  subscriptionCycle?: Cycle; // Obrigatório se chargeType = RECURRENT
  maxInstallmentCount?: number;
  dueDateLimitDays?: number;
  externalReference?: string;
  notificationEnabled?: boolean;
  // Configurações de desconto
  discount?: {
    value: number;
    dueDateLimitDays?: number;
    type?: 'FIXED' | 'PERCENTAGE';
  };
  // Configurações de multa e juros
  fine?: {
    value: number;
    type?: 'FIXED' | 'PERCENTAGE';
  };
  interest?: {
    value: number;
  };
  // Callback
  callback?: {
    successUrl?: string;
    autoRedirect?: boolean;
  };
}

export interface UpdatePaymentLinkInput {
  name?: string;
  description?: string;
  value?: number;
  billingType?: BillingType;
  chargeType?: ChargeType;
  subscriptionCycle?: Cycle;
  maxInstallmentCount?: number;
  dueDateLimitDays?: number;
  externalReference?: string;
  notificationEnabled?: boolean;
  active?: boolean;
}

// ============================================================================
// PAYMENT (COBRANÇA)
// ============================================================================

export interface AsaasPayment {
  id: string;
  customer: string;
  subscription?: string;
  installment?: string;
  paymentLink?: string;
  value: number;
  netValue: number;
  originalValue?: number | null;
  interestValue?: number | null;
  billingType: BillingType;
  status: PaymentStatus;
  dueDate: string;
  originalDueDate?: string;
  paymentDate?: string;
  clientPaymentDate?: string;
  confirmedDate?: string;
  creditDate?: string;
  estimatedCreditDate?: string;
  invoiceUrl?: string;
  bankSlipUrl?: string;
  transactionReceiptUrl?: string;
  invoiceNumber?: string;
  nossoNumero?: string | null;
  description?: string;
  externalReference?: string;
  installmentCount?: number | null;
  installmentNumber?: number | null;
  dateCreated: string;
  deleted?: boolean;
  anticipated?: boolean;
  anticipable?: boolean;
  canBePaidAfterDueDate?: boolean;
  // PIX - pixTransaction é string UUID (id da transação), não objeto
  pixTransaction?: string | null;
  pixQrCodeId?: string | null;
  // Desconto, multa e juros retornados na resposta
  discount?: {
    value: number;
    limitDate?: string | null;
    dueDateLimitDays?: number;
    type?: 'FIXED' | 'PERCENTAGE';
  };
  fine?: {
    value: number;
    type?: 'FIXED' | 'PERCENTAGE';
  };
  interest?: {
    value: number;
    type?: 'PERCENTAGE';
  };
  postalService?: boolean;
  refunds?: unknown[] | null;
}

export interface CreatePaymentInput {
  customer: string;
  billingType: BillingType;
  value: number;
  dueDate: string; // YYYY-MM-DD
  description?: string;
  externalReference?: string;
  // Parcelamento
  installmentCount?: number;
  installmentValue?: number;
  // Desconto
  discount?: {
    value: number;
    dueDateLimitDays?: number;
    type?: 'FIXED' | 'PERCENTAGE';
  };
  // Multa e juros
  fine?: {
    value: number;
    type?: 'FIXED' | 'PERCENTAGE';
  };
  interest?: {
    value: number;
  };
}

// ============================================================================
// WEBHOOK TYPES
// ============================================================================

export interface AsaasWebhookPayload {
  event: AsaasWebhookEvent;
  payment?: AsaasPayment;
  subscription?: AsaasSubscription;
}

export type AsaasWebhookEvent =
  | 'PAYMENT_CREATED'
  | 'PAYMENT_AWAITING_RISK_ANALYSIS'
  | 'PAYMENT_APPROVED_BY_RISK_ANALYSIS'
  | 'PAYMENT_REPROVED_BY_RISK_ANALYSIS'
  | 'PAYMENT_AUTHORIZED'
  | 'PAYMENT_UPDATED'
  | 'PAYMENT_CONFIRMED'
  | 'PAYMENT_RECEIVED'
  | 'PAYMENT_CREDIT_CARD_CAPTURE_REFUSED'
  | 'PAYMENT_ANTICIPATED'
  | 'PAYMENT_OVERDUE'
  | 'PAYMENT_DELETED'
  | 'PAYMENT_RESTORED'
  | 'PAYMENT_REFUNDED'
  | 'PAYMENT_PARTIALLY_REFUNDED'
  | 'PAYMENT_REFUND_IN_PROGRESS'
  | 'PAYMENT_RECEIVED_IN_CASH_UNDONE'
  | 'PAYMENT_CHARGEBACK_REQUESTED'
  | 'PAYMENT_CHARGEBACK_DISPUTE'
  | 'PAYMENT_AWAITING_CHARGEBACK_REVERSAL'
  | 'PAYMENT_DUNNING_RECEIVED'
  | 'PAYMENT_DUNNING_REQUESTED'
  | 'PAYMENT_BANK_SLIP_VIEWED'
  | 'PAYMENT_CHECKOUT_VIEWED'
  | 'PAYMENT_SPLIT_DIVERGENCE_BLOCK'
  | 'PAYMENT_SPLIT_DIVERGENCE_BLOCK_FINISHED';

// ============================================================================
// API RESPONSE TYPES
// ============================================================================

export interface AsaasListResponse<T> {
  object: string;
  hasMore: boolean;
  totalCount: number;
  limit: number;
  offset: number;
  data: T[];
}

export interface AsaasError {
  errors: Array<{
    code: string;
    description: string;
  }>;
}

// ============================================================================
// FILTERS
// ============================================================================

export interface ListPaymentsFilter {
  customer?: string;
  subscription?: string;
  installment?: string;
  status?: PaymentStatus | string;
  billingType?: BillingType | string;
  'dueDate[ge]'?: string; // YYYY-MM-DD - Data de vencimento >=
  'dueDate[le]'?: string; // YYYY-MM-DD - Data de vencimento <=
  'paymentDate[ge]'?: string; // YYYY-MM-DD - Data de pagamento >=
  'paymentDate[le]'?: string; // YYYY-MM-DD - Data de pagamento <=
  'dateCreated[ge]'?: string; // YYYY-MM-DD - Data de criação >=
  'dateCreated[le]'?: string; // YYYY-MM-DD - Data de criação <=
  externalReference?: string;
  offset?: number;
  limit?: number;
}

// ============================================================================
// DOCUMENTS (documentos anexados a cobranças)
// ============================================================================

export interface AsaasDocument {
  id: string;
  name: string;
  availableAfterPayment: boolean;
  type: string;
  file?: {
    publicAccessUrl?: string;
    downloadUrl?: string;
  };
}
