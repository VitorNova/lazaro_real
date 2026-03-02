// Client
export { GoogleCalendarClient, createGoogleCalendarClient } from './client';

// Multi-Calendar Client (for multiple accounts with priority)
export {
  MultiCalendarClient,
  createMultiCalendarClient,
  createMultiCalendarClientFromAccounts,
  type GoogleAccount,
  type MultiCalendarConfig,
  type MultiCalendarAvailabilityResult,
  type MultiCalendarEventResult,
  type AvailabilityScenario,
} from './multi-calendar';

// Types
export {
  // Config
  type CalendarConfig,

  // Event Types
  type CalendarEvent,
  type EventDateTime,
  type Attendee,
  type AttendeeResponseStatus,
  type EventStatus,

  // Conference Data
  type ConferenceData,
  type EntryPoint,
  type ConferenceSolution,

  // Input Types
  type CreateEventInput,
  type UpdateEventInput,

  // Availability Types
  type TimeSlot,
  type AvailabilityResult,
  type AvailabilityParams,

  // NOVO: Agnes Event Metadata (extendedProperties)
  type AgnesEventMetadata,
  type ExtendedProperties,

  // NOVO: Account Schedule Config (horários por agenda)
  type AccountScheduleConfig,

  // Helper Functions
  extractMeetLink,
  formatTimeSlot,
  timeToDate,
  doTimePeriodsOverlap,

  // NOVO: Funções de validação de horário
  timeStringToHours,
  isTimeInAllowedPeriod,
  isDayAllowed,
  validateScheduleTime,
  filterSlotsByPeriod,
  filterSlotsForAgent,
} from './types';
