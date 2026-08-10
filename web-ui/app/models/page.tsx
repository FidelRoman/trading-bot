"use client";
/* Registro de modelos entrenados: métricas fuera de muestra, activación y borrado.

   El modelo activo es el que usa el bot al operar. Se compara siempre contra el
   Buy & Hold del mismo tramo de test para que ninguna cifra se lea sin contexto. */

import { Fragment, useCallback, useEffect, useState } from "react";
import { apiFetch, getJSON, postJSON } from "@/lib/api";
import { MetricsHead, MetricsRow } from "@/components/metrics";
import { isoShort } from "@/lib/format";
import { useLive } from "@/lib/live";
import type {
  InstrumentSpec,
  MarketSelection,
  ModelRecord,
  PaperMetrics,
} from "@/lib/types";

/** Fila de la comparativa; `basis` dice sobre qué curva se midió. */
interface FilaComparativa extends PaperMetrics {
  name: string;
  basis: "per_bar" | "realised";
  error?: string;
}

interface Comparativa {
  ok: boolean;
  error?: string;
  run_id?: string;
  test_range?: string[];
  rows?: FilaComparativa[];
}

export default function ModelsPage() {
  const { refreshStatus } = useLive();
  const [modelos, setModelos] = useState<ModelRecord[]>([]);
  const [activo, setActivo] = useState<string | null>(null);
  const [detalle, setDetalle] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [comparativa, setComparativa] = useState<Comparativa | null>(null);
  const [comparando, setComparando] = useState<string | null>(null);
  const [instrumentos, setInstrumentos] = useState<InstrumentSpec[]>([]);
  const [instrumento, setInstrumento] = useState("all");
  const [vista, setVista] = useState<"models" | "ranking">("models");
  const [seleccion, setSeleccion] = useState<MarketSelection | null>(null);
  const [cargandoRanking, setCargandoRanking] = useState(true);

  const cargar = useCallback(async () => {
    try {
      const r = await getJSON<{ active: string | null; models: ModelRecord[] }>("/api/models");
      setModelos(r.models);
      setActivo(r.active);
    } catch {
      setModelos([]);
    }
  }, []);

  useEffect(() => { cargar(); }, [cargar]);

  useEffect(() => {
    getJSON<{ instruments: InstrumentSpec[] }>("/api/instruments")
      .then((response) => setInstrumentos(response.instruments))
      .catch(() => setInstrumentos([]));
    getJSON<MarketSelection>("/api/selection/latest")
      .then(setSeleccion)
      .catch(() => setSeleccion({ ok: false, error: "No se pudo cargar el ranking" }))
      .finally(() => setCargandoRanking(false));
  }, []);

  const modelosVisibles = instrumento === "all"
    ? modelos
    : modelos.filter((modelo) => modelo.instrument === instrumento);
  const rankingVisible = (seleccion?.ranking ?? []).filter(
    (row) => instrumento === "all" || row.symbol === instrumento
  );

  const activar = async (runId: string) => {
    const r = await postJSON<{ ok: boolean; error?: string }>(`/api/models/${runId}/activate`);
    setAviso(r.ok ? `Modelo activo: ${runId}` : r.error ?? "No se pudo activar");
    await cargar();
    await refreshStatus();
  };

  const desactivar = async () => {
    await postJSON("/api/models/deactivate");
    setAviso("Sin modelo activo: FSRPPO no operará");
    await cargar();
    await refreshStatus();
  };

  const comparar = async (runId: string) => {
    setComparando(runId);
    setComparativa(null);
    const r = await postJSON<Comparativa>("/api/fsrppo/compare", { run_id: runId });
    setComparativa(r);
    setComparando(null);
  };

  const borrar = async (runId: string) => {
    await apiFetch(`/api/models/${runId}`, { method: "DELETE" });
    setAviso(`Modelo ${runId} eliminado`);
    await cargar();
  };

  return (
    <>
      <div className="card">
        <div className="card-head" style={{ flexWrap: "wrap", gap: 12 }}>
          <div style={{ display: "flex", gap: 8 }} role="tablist" aria-label="Vista de modelos">
            <button
              className="btn"
              role="tab"
              aria-selected={vista === "models"}
              onClick={() => setVista("models")}
            >
              MODELOS
            </button>
            <button
              className="btn"
              role="tab"
              aria-selected={vista === "ranking"}
              onClick={() => setVista("ranking")}
            >
              ÚLTIMO RANKING
            </button>
          </div>
          <label className="hint model-filter">
            INSTRUMENTO
            <select
              value={instrumento}
              onChange={(event) => setInstrumento(event.target.value)}
              aria-label="Filtrar por instrumento"
            >
              <option value="all">Todos</option>
              {instrumentos.map((spec) => (
                <option key={spec.symbol} value={spec.symbol}>{spec.symbol}</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {vista === "models" && <>
      <div className="metric-row inner">
        <div className="metric-card">
          <div className="m-lbl">MODELOS</div>
          <div className="m-val">{modelosVisibles.length}</div>
        </div>
        <div className="metric-card">
          <div className="m-lbl">ACTIVO</div>
          <div className="m-val" style={{ fontSize: 14 }}>{activo ?? "ninguno"}</div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div className="card-title">⧉ MODELOS ENTRENADOS</div>
          {activo && <button className="btn" onClick={desactivar}>DESACTIVAR</button>}
        </div>

        {aviso && <div className="hint" style={{ padding: "6px 12px" }}>{aviso}</div>}

        <div className="table-wrap">
          <table>
            <MetricsHead first="MODELO (TEST)" extra={["OPS", "ACCIONES"]} />
            <tbody>
              {modelosVisibles.map((m) => (
                <Fragment key={m.run_id}>
                  <MetricsRow
                    name={
                      <button
                        className="linkish"
                        onClick={() => setDetalle(detalle === m.run_id ? null : m.run_id)}
                        title="Ver detalle"
                      >
                        {m.is_active ? "★ " : ""}{m.run_id}
                      </button>
                    }
                    metrics={m.test_metrics}
                    reference={m.benchmark_metrics}
                    highlight={!!m.is_active}
                    extra={[
                      m.test_metrics?.trades ?? "—",
                      <span key="a" style={{ display: "flex", gap: 6 }}>
                        {!m.is_active && (
                          <button className="btn" onClick={() => activar(m.run_id)}>ACTIVAR</button>
                        )}
                        <button className="btn" onClick={() => comparar(m.run_id)}
                                disabled={comparando === m.run_id}>
                          {comparando === m.run_id ? "…" : "COMPARAR"}
                        </button>
                        <button
                          className="btn danger"
                          onClick={() => borrar(m.run_id)}
                          aria-label={`Eliminar modelo ${m.run_id}`}
                        >✕</button>
                      </span>,
                    ]}
                  />
                  {detalle === m.run_id && (
                    <tr>
                      <td colSpan={10} style={{ background: "rgba(148,163,184,.05)" }}>
                        <div style={{ display: "grid", gap: 10, padding: "8px 4px" }}>
                          <div className="hint">
                            Entrenado {isoShort(m.created_at)} · {m.instrument} {m.timeframe} ·
                            train {m.train_range[0]?.slice(0, 10)} → {m.train_range[1]?.slice(0, 10)} ·
                            test {m.test_range[0]?.slice(0, 10)} → {m.test_range[1]?.slice(0, 10)}
                          </div>
                          <table>
                            <MetricsHead first="TRAMO" />
                            <tbody>
                              <MetricsRow name="Train" metrics={m.train_metrics} />
                              <MetricsRow name="Test" metrics={m.test_metrics} />
                              <MetricsRow name="Buy & Hold (test)" metrics={m.benchmark_metrics} />
                            </tbody>
                          </table>
                          <div className="hint">
                            Una diferencia grande entre train y test es sobreajuste:
                            el modelo recuerda el pasado en vez de haber aprendido algo.
                          </div>
                          <details>
                            <summary className="hint">Hiperparámetros</summary>
                            <pre style={{ fontSize: 11, overflowX: "auto" }}>
{JSON.stringify({ fsr: m.fsr_params, ppo: m.ppo_params, env: m.env_params }, null, 2)}
                            </pre>
                          </details>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
          {modelosVisibles.length === 0 && (
            <div className="empty">
              {modelos.length === 0
                ? "Sin modelos todavía — entrena uno en la pestaña de Entrenamiento"
                : "No hay modelos para el instrumento seleccionado"}
            </div>
          )}
        </div>
      </div>

      {comparativa && (
        <div className="card">
          <div className="card-head">
            <div className="card-title">⇄ COMPARATIVA SOBRE EL TRAMO DE TEST</div>
            {comparativa.test_range && (
              <span className="chip">
                {comparativa.test_range[0]?.slice(0, 10)} → {comparativa.test_range[1]?.slice(0, 10)}
              </span>
            )}
          </div>

          {!comparativa.ok ? (
            <div className="empty neg">{comparativa.error}</div>
          ) : (
            <>
              <div className="table-wrap">
                <table>
                  <MetricsHead first="ESTRATEGIA" extra={["OPS", "VALORACIÓN"]} />
                  <tbody>
                    {comparativa.rows?.map((fila) => (
                      <MetricsRow
                        key={fila.name}
                        name={fila.error ? `${fila.name} (falló)` : fila.name}
                        metrics={fila}
                        reference={comparativa.rows?.find((f) => f.name === "Buy & Hold")}
                        highlight={fila.name === "FSRPPO"}
                        extra={[
                          fila.trades ?? "—",
                          fila.basis === "per_bar" ? "barra a barra" : "solo al cerrar",
                        ]}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="hint" style={{ padding: "8px 12px" }}>
                FSRPPO y Buy &amp; Hold se valoran a mercado en cada barra; las
                estrategias por regla solo registran equity al cerrar cada
                operación. Sobre esa curva a saltos la volatilidad no es
                comparable, así que su Sharpe, Calmar y Sortino se dejan vacíos
                en vez de publicar cifras que parecerían equivalentes sin serlo.
                CRR, máxima caída y número de operaciones sí son comparables.
              </div>
            </>
          )}
        </div>
      )}
      </>}

      {vista === "ranking" && (
        <div className="card">
          <div className="card-head">
            <div className="card-title">RANKING DE VALIDACIÓN</div>
            {seleccion?.created_at && (
              <span className="chip">{isoShort(seleccion.created_at)}</span>
            )}
          </div>

          {cargandoRanking ? (
            <div className="empty" role="status">Cargando último barrido…</div>
          ) : !seleccion?.ok ? (
            <div className="empty">{seleccion?.error ?? "Todavía no hay barridos"}</div>
          ) : (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>RANK</th>
                      <th>INSTRUMENTO</th>
                      <th>TF</th>
                      <th>SHARPE MEDIANO</th>
                      <th>CRR MEDIANO</th>
                      <th>CRR B&amp;H</th>
                      <th>ESTADO</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rankingVisible.map((row) => (
                      <tr key={`${row.symbol}-${row.timeframe}`} className={row.winner ? "ranking-winner" : ""}>
                        <td>{row.rank}</td>
                        <td>{row.winner ? "GANADORA · " : ""}{row.symbol}</td>
                        <td>{row.timeframe.toUpperCase()}</td>
                        <td>{row.validation.median_sharpe?.toFixed(3) ?? "—"}</td>
                        <td>
                          {row.validation.median_crr == null
                            ? "—"
                            : `${(row.validation.median_crr * 100).toFixed(2)}%`}
                        </td>
                        <td>
                          {row.validation.benchmark_crr == null
                            ? "—"
                            : `${(row.validation.benchmark_crr * 100).toFixed(2)}%`}
                        </td>
                        <td>{row.eligible ? "CRR > B&H" : "No supera B&H"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {rankingVisible.length === 0 && (
                  <div className="empty">No hay resultados para el instrumento seleccionado</div>
                )}
              </div>

              <div className="hint" style={{ padding: "10px 12px" }}>
                El ranking usa exclusivamente el 20 % de validación: Sharpe mediano
                entre semillas y CRR superior a Buy &amp; Hold. El 20 % de test se
                evalúa solo para la combinación ganadora.
                {seleccion.test && (
                  <> Resultado final: {seleccion.test.passed}/{seleccion.test.total} semillas
                    (mínimo {seleccion.test.required});
                    {seleccion.test.accepted ? " criterio aprobado." : " criterio no aprobado."}</>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </>
  );
}
