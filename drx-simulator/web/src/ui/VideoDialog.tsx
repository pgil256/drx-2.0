import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { useAppStore } from '@/store/useAppStore';

type VideoEntry = { src: string; title: string };

const VIDEOS: VideoEntry[] = [];

export function VideoDialog() {
  const open = useAppStore((s) => s.ui.videoOpen);
  const setUi = useAppStore((s) => s.setUi);
  const [index, setIndex] = useState(0);

  const close = (next: boolean) => setUi({ videoOpen: next });
  const current = VIDEOS[index];

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{current?.title ?? 'Instructional Videos'}</DialogTitle>
          {!current && (
            <DialogDescription>
              No videos are configured. Drop MP4s into <code>public/videos/</code> and register
              them in <code>src/ui/VideoDialog.tsx</code>.
            </DialogDescription>
          )}
        </DialogHeader>

        {current ? (
          <video
            key={current.src}
            src={current.src}
            controls
            autoPlay
            className="w-full rounded-md bg-black aspect-video"
          />
        ) : (
          <div className="aspect-video rounded-md border border-white/10 bg-black/40 flex items-center justify-center text-white/40 text-sm">
            No video available
          </div>
        )}

        {VIDEOS.length > 1 && (
          <div className="flex items-center justify-between pt-2">
            <Button
              variant="outline"
              onClick={() => setIndex((i) => (i - 1 + VIDEOS.length) % VIDEOS.length)}
            >
              Previous
            </Button>
            <div className="text-xs text-white/50">
              {index + 1} / {VIDEOS.length}
            </div>
            <Button variant="outline" onClick={() => setIndex((i) => (i + 1) % VIDEOS.length)}>
              Next
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
