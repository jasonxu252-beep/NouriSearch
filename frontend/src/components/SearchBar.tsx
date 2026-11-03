import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { searchFoods, type FoodSearchResult, type FoodType } from "../api/client";
import { t } from "../i18n";

export const FOOD_TYPES: readonly FoodType[] = [
  "all",
  "whole_foods",
  "fruits",
  "vegetables",
  "proteins",
  "grains",
  "dishes",
  "ingredients",
];

const SUGGESTION_DELAY_MS = 200;

export function parseFoodType(value: string | null): FoodType {
  return FOOD_TYPES.find((type) => type === value) ?? "all";
}

/** The search bar from the sketches, with the suggestions and filter row the plan adds. */
export function SearchBar() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const urlQuery = params.get("q") ?? "";
  const foodType = parseFoodType(params.get("type"));

  const inputId = useId();
  const listId = useId();
  const [query, setQuery] = useState(urlQuery);
  const [suggestions, setSuggestions] = useState<FoodSearchResult[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const blurTimer = useRef<number | undefined>(undefined);

  useEffect(() => setQuery(urlQuery), [urlQuery]);

  useEffect(() => {
    const text = query.trim();
    if (!isOpen || text.length < 2) {
      setSuggestions([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      searchFoods(text, foodType, { limit: 6, signal: controller.signal })
        .then((response) => {
          setSuggestions(response.results);
          setActive(-1);
        })
        .catch(() => {
          // Suggestions are a convenience, so a failure simply shows none.
          if (!controller.signal.aborted) setSuggestions([]);
        });
    }, SUGGESTION_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, foodType, isOpen]);

  useEffect(() => () => window.clearTimeout(blurTimer.current), []);

  function goToResults(type: FoodType = foodType) {
    setIsOpen(false);
    const text = query.trim();
    if (!text) return;
    const next = new URLSearchParams({ q: text });
    if (type !== "all") next.set("type", type);
    navigate(`/?${next.toString()}`);
  }

  function chooseFilter(type: FoodType) {
    setIsOpen(false);
    const text = query.trim();
    const next = new URLSearchParams();
    if (text) next.set("q", text);
    if (type !== "all") next.set("type", type);
    const search = next.toString();
    navigate(search ? `/?${search}` : "/");
  }

  function openFood(food: FoodSearchResult) {
    setIsOpen(false);
    navigate(`/foods/${food.id}`);
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const chosen = suggestions[active];
    if (isOpen && chosen) openFood(chosen);
    else goToResults();
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    const showing = isOpen && suggestions.length > 0;
    if (event.key === "ArrowDown" && showing) {
      event.preventDefault();
      setActive((active + 1) % suggestions.length);
    } else if (event.key === "ArrowUp" && showing) {
      event.preventDefault();
      setActive((active - 1 + suggestions.length) % suggestions.length);
    } else if (event.key === "Escape" && isOpen) {
      event.stopPropagation();
      setIsOpen(false);
    }
  }

  const showList = isOpen && suggestions.length > 0;

  return (
    <div className="search">
      <form className="search__form" role="search" onSubmit={onSubmit}>
        <label htmlFor={inputId} className="visually-hidden">
          {t("search.label")}
        </label>
        <input
          id={inputId}
          className="search__input"
          type="search"
          role="combobox"
          autoComplete="off"
          placeholder={t("search.placeholder")}
          value={query}
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showList && active >= 0 ? `${listId}-${active}` : undefined}
          onChange={(event) => {
            setQuery(event.target.value);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          onBlur={() => {
            // A click on a suggestion lands after the input blurs.
            blurTimer.current = window.setTimeout(() => setIsOpen(false), 150);
          }}
          onKeyDown={onKeyDown}
        />
        <button type="submit" className="search__button" aria-label={t("search.submit")}>
          <svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true">
            <path
              d="M3 10h13m-5-5 5 5-5 5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
        <button
          type="button"
          className="search__button"
          disabled
          title={t("search.cameraUnavailable")}
          aria-label={`${t("search.camera")}. ${t("search.cameraUnavailable")}`}
        >
          <svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true">
            <path
              d="M2.5 6.5h3l1.5-2h6l1.5 2h3v9.5h-15z"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
            <circle cx="10" cy="11" r="3" fill="none" stroke="currentColor" strokeWidth="1.6" />
          </svg>
        </button>
        <ul
          id={listId}
          role="listbox"
          aria-label={t("search.suggestions")}
          className="suggestions"
          hidden={!showList}
        >
          {suggestions.map((food, index) => (
            // Keyboard selection happens through the combobox, which is how this pattern works.
            // eslint-disable-next-line jsx-a11y/click-events-have-key-events
            <li
              key={food.id}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === active}
              className="suggestions__item"
              data-active={index === active || undefined}
              onClick={() => openFood(food)}
            >
              <span>{food.name}</span>
              <span className="suggestions__meta">{t(`level.${food.processing_level}`)}</span>
            </li>
          ))}
        </ul>
      </form>

      <fieldset className="filters">
        <legend className="visually-hidden">{t("search.filters")}</legend>
        {FOOD_TYPES.map((type) => (
          <label
            key={type}
            className="filters__option"
            data-checked={type === foodType || undefined}
          >
            <input
              type="radio"
              name="food-type"
              className="visually-hidden"
              checked={type === foodType}
              onChange={() => chooseFilter(type)}
            />
            {t(`filter.${type}`)}
          </label>
        ))}
      </fieldset>
    </div>
  );
}
