import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Dialog } from '../ui/Dialog'

export interface LightboxState {
  images: string[]
  index: number
  title?: string
}

interface PhotoLightboxProps {
  state: LightboxState | null
  onIndexChange: (index: number) => void
  onClose: () => void
}

// Leaflet popups are too small to show a photo at any real size - click a thumbnail there to
// open it here, full-size, with prev/next when a track status carries more than one photo.
export function PhotoLightbox({ state, onIndexChange, onClose }: PhotoLightboxProps) {
  const images = state?.images ?? []
  const index = state?.index ?? 0
  const multi = images.length > 1
  const title = state?.title ?? 'Photo'

  return (
    <Dialog
      open={images.length > 0}
      onOpenChange={(open) => !open && onClose()}
      title={multi ? `${title} · ${index + 1}/${images.length}` : title}
    >
      {images.length > 0 && (
        <div className="relative">
          <img
            src={images[index]}
            alt={title}
            className="max-h-[70vh] w-full rounded-lg bg-panel object-contain"
          />
          {multi && (
            <>
              <button
                onClick={() => onIndexChange((index - 1 + images.length) % images.length)}
                aria-label="Previous photo"
                className="absolute left-2 top-1/2 -translate-y-1/2 rounded-full border border-hairline bg-panel/90 p-2 text-ink shadow backdrop-blur transition-colors hover:bg-surface"
              >
                <ChevronLeft size={18} />
              </button>
              <button
                onClick={() => onIndexChange((index + 1) % images.length)}
                aria-label="Next photo"
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full border border-hairline bg-panel/90 p-2 text-ink shadow backdrop-blur transition-colors hover:bg-surface"
              >
                <ChevronRight size={18} />
              </button>
            </>
          )}
        </div>
      )}
    </Dialog>
  )
}
