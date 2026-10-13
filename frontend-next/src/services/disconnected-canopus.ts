import type { CanopusService, CanopusStreamEvent } from "@/domain/canopus";

export const CANOPUS_NOT_CONNECTED =
  "Canopus is not connected to a backend yet. No answer was generated.";

/**
 * The connected product has no Canopus conversation backend yet. This adapter never
 * produces text: any request fails with a plain statement, so no reply can be mistaken
 * for an AI answer. Replace it with the real adapter when the Canopus API exists.
 */
export class DisconnectedCanopusService implements CanopusService {
  // eslint-disable-next-line require-yield
  async *stream(): AsyncIterable<CanopusStreamEvent> {
    throw new Error(CANOPUS_NOT_CONNECTED);
  }
}
