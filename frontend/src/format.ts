export const number = (value: number | null | undefined) =>
  value == null ? "—" : new Intl.NumberFormat("pt-BR").format(value);
export const timestamp = (value: string | null | undefined) =>
  value
    ? Number.isNaN(new Date(value).getTime())
      ? value
      : new Date(value).toLocaleString("pt-BR")
    : "Não informado";
