/**
 * Redis Services Index
 *
 * Re-exporta todos os servicos Redis
 */

// Client
export {
  getRedisConnection,
  createRedisConnection,
  closeRedisConnection,
  isRedisAvailable
} from './client';

// Message Buffer Service
export {
  MessageBufferService,
  getMessageBufferService,
  type BufferedMessage,
  type BufferMediaEntry
} from './message-buffer.service';

// Lock Service
export {
  LockService,
  getLockService
} from './lock.service';

// Buffer Processor Service
export {
  BufferProcessorService,
  getBufferProcessorService,
  type BufferProcessorConfig,
  type BufferProcessResult,
  type MessageInput
} from './buffer-processor.service';
