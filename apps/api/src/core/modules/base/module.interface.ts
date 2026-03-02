/**
 * Interface base para módulos - SIMPLIFICADA
 */

export type ModuleStatus = 'idle' | 'ready' | 'error';

export interface ModuleHealth {
  healthy: boolean;
  message?: string;
}

export interface IModule {
  readonly name: string;
  status: ModuleStatus;
  initialize(): Promise<void>;
  shutdown(): Promise<void>;
  healthCheck(): Promise<ModuleHealth>;
}
