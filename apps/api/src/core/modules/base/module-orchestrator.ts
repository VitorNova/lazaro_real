/**
 * Module Orchestrator - SIMPLIFICADO
 */

import { IModule, ModuleHealth } from './module.interface';

export class ModuleOrchestrator {
  private modules: Map<string, IModule> = new Map();

  register(module: IModule): void {
    this.modules.set(module.name, module);
  }

  get<T extends IModule>(name: string): T | undefined {
    return this.modules.get(name) as T | undefined;
  }

  async initializeAll(): Promise<void> {
    const entries = Array.from(this.modules.entries());
    for (const [name, module] of entries) {
      console.log(`[Modules] Initializing ${name}...`);
      await module.initialize();
    }
    console.log('[Modules] All modules initialized');
  }

  async shutdownAll(): Promise<void> {
    const modules = Array.from(this.modules.values()).reverse();
    for (const module of modules) {
      await module.shutdown();
    }
    console.log('[Modules] All modules shut down');
  }

  async healthCheck(): Promise<Record<string, ModuleHealth>> {
    const results: Record<string, ModuleHealth> = {};
    const entries = Array.from(this.modules.entries());
    for (const [name, module] of entries) {
      results[name] = await module.healthCheck();
    }
    return results;
  }
}

let instance: ModuleOrchestrator | null = null;

export function getModuleOrchestrator(): ModuleOrchestrator {
  if (!instance) {
    instance = new ModuleOrchestrator();
  }
  return instance;
}
