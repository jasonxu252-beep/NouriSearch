import { useState } from "react";

import type { FoodImage } from "../api/client";
import { t } from "../i18n";

interface Props {
  foodName: string;
  images: readonly FoodImage[];
}

/** Every image shows its credit, because every displayed image must be attributable. */
export function ImageCarousel({ foodName, images }: Props) {
  const [index, setIndex] = useState(0);
  const image = images[index];

  return (
    <figure className="carousel" aria-label={t("overview.images", { food: foodName })}>
      <div className="carousel__stage">
        {image ? (
          <img className="carousel__image" src={image.url} alt={foodName} />
        ) : (
          <p className="carousel__empty">{t("overview.noImage")}</p>
        )}
        {images.length > 1 && (
          <>
            <button
              type="button"
              className="carousel__arrow carousel__arrow--previous"
              aria-label={t("overview.previousImage")}
              onClick={() => setIndex((index - 1 + images.length) % images.length)}
            >
              {"‹"}
            </button>
            <button
              type="button"
              className="carousel__arrow carousel__arrow--next"
              aria-label={t("overview.nextImage")}
              onClick={() => setIndex((index + 1) % images.length)}
            >
              {"›"}
            </button>
          </>
        )}
      </div>
      {image && (
        <figcaption className="carousel__credit">
          {images.length > 1 && (
            <span>{t("overview.imageOf", { position: index + 1, total: images.length })} </span>
          )}
          {t("overview.imageCredit", { attribution: image.attribution, license: image.license })}
        </figcaption>
      )}
    </figure>
  );
}
