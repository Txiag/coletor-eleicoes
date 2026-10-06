import { useEffect, useState } from "react";
import { query, useResource } from "../useResource";
import type { Page } from "../types";
import SearchSelect from "./SearchSelect";
import type { Option } from "./SearchSelect";

export default function RemoteFilter({ label, level, value, context, disabled, onChange, onResolveLabel }: {
  label: string; level: string; value: string; context: Record<string, string>; disabled?: boolean;
  onChange: (value: string, label: string) => void; onResolveLabel?: (label: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Option>();
  useEffect(() => {
    const timer = setTimeout(() => { setDebounced(search); setPage(1); }, 250);
    return () => clearTimeout(timer);
  }, [search]);
  const result = useResource<Page<Option>>(disabled ? null : query("/api/options", {
    ...context, level, q: debounced, page, page_size: 30,
  }));
  const items = result.data?.items || [];
  const selectedResult = useResource<Page<Option>>(disabled || !value ? null : query("/api/options", {
    ...context, level, q: value, page_size: 30,
  }));
  const resolved = selectedResult.data?.items.find(item => item.value === value);
  useEffect(() => {
    if (resolved) onResolveLabel?.(resolved.label);
  }, [resolved, onResolveLabel]);
  const pending = search !== debounced || result.loading;
  return <SearchSelect label={label} value={value} disabled={disabled}
    selectedLabel={resolved?.label || (selected?.value === value ? selected.label : value || "Todos")}
    options={[{ value: "", label: "Todos" }, ...(pending ? [] : items)]}
    onSearch={setSearch} loading={pending} error={result.error}
    onChange={(next, nextLabel) => { setSelected({ value: next, label: nextLabel }); onChange(next, nextLabel); }}
    footer={<div className="mini-pagination">
      <button type="button" disabled={pending || page === 1} onClick={() => setPage(p => p - 1)}>Anterior</button>
      <span>{page} / {Math.max(1, Math.ceil((result.data?.total || 0) / 30))}</span>
      <button type="button" disabled={pending || page * 30 >= (result.data?.total || 0)} onClick={() => setPage(p => p + 1)}>Mais opções</button>
    </div>} />;
}