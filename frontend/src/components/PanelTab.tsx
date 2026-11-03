import { t } from "../i18n";

/** The folder tab from the sketches. Translation arrives in milestone 7, so it says so for now. */
export function PanelTab() {
  return (
    <button
      type="button"
      className="panel__tab"
      disabled
      title={t("panel.translateUnavailable")}
      aria-label={`${t("panel.translate")}. ${t("panel.translateUnavailable")}`}
    >
      {t("panel.translate")}
    </button>
  );
}
