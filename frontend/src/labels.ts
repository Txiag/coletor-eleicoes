const categories: Record<string, string> = {
  nominal: "Votos nominais",
  branco: "Brancos",
  nulo: "Nulos",
  legenda: "Votos de legenda",
  cargo_sem_candidato: "Cargo sem candidato",
  blank: "Brancos",
  null: "Nulos",
  legend: "Votos de legenda",
};
export const categoryLabel = (value: string) => categories[value] || value;
