/**
 * MediaPreview — handles image/video display with broken-URL fallback.
 *
 * Shows the media if the URL loads.
 * Falls back to a placeholder if the URL is missing or fails to load.
 * Works for both images and videos (detected from URL extension or file_type).
 */
"use client";
import { useState } from "react";
import { ImageIcon, Film } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  url?: string | null;
  fileType?: "image" | "video" | null;
  /** Extra classes for the outer container */
  className?: string;
  /** Extra classes on the img/video element itself */
  mediaClassName?: string;
  /** Show native controls on video. Default: false (thumbnail mode) */
  controls?: boolean;
  /** Mute video (used for card thumbnails). Default: true */
  muted?: boolean;
  /** Alt text for images */
  alt?: string;
  /** Size of placeholder icon. Default: 28 */
  iconSize?: number;
}

function isVideoUrl(url: string) {
  return /\.(mp4|webm|mov)(\?.*)?$/i.test(url);
}

export function MediaPreview({
  url,
  fileType,
  className,
  mediaClassName,
  controls = false,
  muted = true,
  alt = "",
  iconSize = 28,
}: Props) {
  const [imgError, setImgError] = useState(false);

  const containerCls = cn("w-full h-full bg-gray-100 flex items-center justify-center", className);
  const mediaCls = cn("w-full h-full object-cover", mediaClassName);

  // Determine type: explicit fileType beats URL sniffing
  const isVid =
    fileType === "video" ||
    (!fileType && url ? isVideoUrl(url) : false);

  // No URL at all — placeholder
  if (!url) {
    return (
      <div className={containerCls}>
        <Placeholder isVideo={isVid} iconSize={iconSize} />
      </div>
    );
  }

  // Video
  if (isVid) {
    return (
      <div className={cn("w-full h-full bg-black relative", className)}>
        <video
          src={url}
          className={mediaCls}
          controls={controls}
          muted={muted}
          playsInline
          preload="metadata"
          onError={(e) => {
            // Hide broken video, show placeholder
            const vid = e.currentTarget;
            vid.style.display = "none";
            const ph = vid.nextSibling as HTMLElement | null;
            if (ph) ph.style.display = "flex";
          }}
        />
        {/* Sibling placeholder, hidden unless video errors */}
        <div
          className="absolute inset-0 bg-gray-100 items-center justify-center hidden"
          aria-hidden
        >
          <Placeholder isVideo iconSize={iconSize} />
        </div>
      </div>
    );
  }

  // Image
  if (imgError) {
    return (
      <div className={containerCls}>
        <Placeholder isVideo={false} iconSize={iconSize} />
      </div>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={url}
      alt={alt}
      className={cn(mediaCls, className)}
      onError={() => setImgError(true)}
    />
  );
}

function Placeholder({ isVideo, iconSize }: { isVideo: boolean; iconSize: number }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1.5 text-gray-300 w-full h-full">
      {isVideo
        ? <Film size={iconSize} />
        : <ImageIcon size={iconSize} />
      }
      <span className="text-[10px] font-medium">{isVideo ? "No video" : "No media"}</span>
    </div>
  );
}
