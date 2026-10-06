import { useEffect, useId, useState } from "react";
import type { ReactNode } from "react";

export type Option = { value: string; label: string };
const normalize = (text: string) => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("pt-BR");

export default function SearchSelect({ label, value, options, selectedLabel, disabled, onChange, onSearch, loading, error, footer }: {
  label: string; value: string; options: Option[]; selectedLabel?: string; disabled?: boolean;
  onChange: (value: string, label: string) => void; onSearch?: (search: string) => void;
  loading?: boolean; error?: string; footer?: ReactNode;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [active, setActive] = useState(-1);
  const text = options.find(option => option.value === value)?.label || selectedLabel || value;
  const items = onSearch ? options : options.filter(option => normalize(`${option.label} ${option.value}`).includes(normalize(search)));
  const expanded = open && !disabled;
  function close() { setOpen(false); setSearch(""); setActive(-1); onSearch?.(""); }
  function choose(option: Option) { onChange(option.value, option.label); close(); }
  useEffect(() => { setActive(-1); }, [search, options]);
  useEffect(() => {
    if (active >= 0) document.getElementById(`${id}-option-${active}`)?.scrollIntoView?.({ block: "nearest" });
  }, [active, id]);
  return <div className="search-select" onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget)) close();
  }}>
    <label htmlFor={id}>{label}</label>
    <input id={id} role="combobox" autoComplete="off" disabled={disabled}
      aria-expanded={expanded} aria-controls={`${id}-options`} aria-autocomplete="list"
      aria-activedescendant={expanded && active >= 0 && items[active] ? `${id}-option-${active}` : undefined}
      value={expanded ? search : text} placeholder={expanded ? "Digite para buscar…" : "Selecione…"}
      onFocus={() => { if (!open) { setOpen(true); setSearch(""); setActive(-1); } }}
      onClick={() => setOpen(true)}
      onChange={event => { setOpen(true); setSearch(event.target.value); setActive(-1); onSearch?.(event.target.value); }}
      onKeyDown={event => {
        if (event.key === "Escape") { event.preventDefault(); close(); }
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault(); setOpen(true);
          setActive(index => items.length ? (event.key === "ArrowDown" ? Math.min(index + 1, items.length - 1) : index < 0 ? items.length - 1 : Math.max(index - 1, 0)) : -1);
        }
        if (event.key === "Enter" && expanded) { event.preventDefault(); if (items[active]) choose(items[active]); }
      }} />
    {expanded && <div className="select-popup">
      <ul id={`${id}-options`} role="listbox" aria-label={label} aria-busy={loading}>
        {items.map((option, index) => <li id={`${id}-option-${index}`} key={option.value} role="option"
          aria-selected={option.value === value} className={active === index ? "highlighted" : ""}
          onMouseDown={event => event.preventDefault()} onMouseMove={() => setActive(index)} onClick={() => choose(option)}>{option.label}</li>)}
      </ul>
      {loading && <small role="status">Buscando opções…</small>}
      {!loading && !items.length && <small role="status">Nenhuma opção encontrada.</small>}
      {error && <small role="alert">{error}</small>}
      {footer}
    </div>}
  </div>;
}
