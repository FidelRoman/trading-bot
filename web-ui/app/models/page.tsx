"use client";
/* Registro de modelos entrenados: métricas fuera de muestra, activación y borrado.

   El modelo activo es el que usa el bot al operar. Se compara siempre contra el
   Buy & Hold del mismo tramo de test para que ninguna cifra se lea sin contexto. */

import { Fragment, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import ConfirmDialog from "@/components/ConfirmDialog";
import { MetricsHead, MetricsRow } from "@/components/metrics";
import TrainingParams from "@/components/TrainingParams";
import AssetBadge from "@/components/ui/AssetBadge";
import EmptyState from "@/components/ui/EmptyState";
import Icon from "@/components/ui/Icon";
import Mark from "@/components/ui/Mark";
import Notice from "@/components/ui/Notice";
import { Panel } from "@/components/ui/Panel";
import Readout, { ReadoutRow } from "@/components/ui/Readout";
import Skeleton from "@/components/ui/Skeleton";
import Tabs from "@/components/ui/Tabs";
import { TableFrame } from "@/components/ui/Table";
import { useToast } from "@/components/ui/Toast";
import { apiFetch, getJSON, postJSON } from "@/lib/api";
import { isoShort } from "@/lib/format";
import { useLive } from "@/lib/live";
import type { InstrumentSpec, MarketSelection, ModelRecord, PaperMetrics } from "@/lib/types";

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
  const { push } = useToast();
  const [modelos, setModelos] = useState<ModelRecord[] | null>(null);
  // Un activo por instrumento: el mapa símbolo → run_id que devuelve la API.
  const [activos, setActivos] = useState<Record<string, string>>({});
  const [instrumentoActual, setInstrumentoActual] = useState<string | null>(null);
  const [detalle, setDetalle] = useState<string | null>(null);
  const [comparativa, setComparativa] = useState<Comparativa | null>(null);
  const [comparando, setComparando] = useState<string | null>(null);
  const [instrumentos, setInstrumentos] = useState<InstrumentSpec[]>([]);
  const [instrumento, setInstrumento] = useState("all");
  const [vista, setVista] = useState<"models" | "ranking">("models");
  const [seleccion, setSeleccion] = useState<MarketSelection | null>(null);
  const [cargandoRanking, setCargandoRanking] = useState(true);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const cargar = useCallback(async () => {
    try {
      const r = await getJSON<{
        active: Record<string, string>;
        current_instrument?: string;
        models: ModelRecord[];
      }>("/api/models");
      setModelos(r.models);
      setActivos(r.active ?? {});
      setInstrumentoActual(r.current_instrument ?? null);
    } catch {
      setModelos([]);
    }
  }, []);

  useEffect(() => {
    cargar();
  }, [cargar]);

  useEffect(() => {
    getJSON<{ instruments: InstrumentSpec[] }>("/api/instruments")
      .then((response) => setInstrumentos(response.instruments))
      .catch(() => setInstrumentos([]));
    getJSON<MarketSelection>("/api/selection/latest")
      .then(setSeleccion)
      .catch(() => setSeleccion({ ok: false, error: "No se pudo cargar el ranking" }))
      .finally(() => setCargandoRanking(false));
  }, []);

  const lista = modelos ?? [];
  const modelosVisibles =
    instrumento === "all" ? lista : lista.filter((modelo) => modelo.instrument === instrumento);
  const rankingVisible = (seleccion?.ranking ?? []).filter(
    (row) => instrumento === "all" || row.symbol === instrumento
  );
  const parejasActivas = Object.entries(activos).filter(
    ([simbolo]) => instrumento === "all" || simbolo === instrumento
  );

  const activar = async (runId: string) => {
    const r = await postJSON<{
      ok: boolean;
      error?: string;
      instrument?: string;
      meets_acceptance?: boolean;
    }>(`/api/models/${runId}/activate`);
    // El instrumento lo decide el modelo, no el filtro que esté puesto: si no se
    // dijera, activar desde "Todos" parecería haber armado el símbolo en pantalla.
    if (r.ok) {
      push(
        `${runId} es ahora el modelo activo de ${r.instrument}. ${
          r.meets_acceptance
            ? "Cumple el criterio de aceptación."
            : "No cumple el criterio: operará bajo tu responsabilidad."
        }`,
        r.meets_acceptance ? "ok" : "warn"
      );
    } else {
      push(r.error ?? "No se pudo activar el modelo.", "danger");
    }
    await cargar();
    await refreshStatus();
  };

  const desactivar = async (simbolo: string) => {
    await postJSON("/api/models/deactivate", { instrument: simbolo });
    push(`Sin modelo activo para ${simbolo}: FSRPPO no operará ese instrumento.`, "warn");
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

  const borrar = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      const response = await apiFetch(`/api/models/${pendingDelete}`, { method: "DELETE" });
      if (!response.ok) throw new Error("No se pudo eliminar el modelo.");
      push(`Modelo ${pendingDelete} eliminado.`);
      setPendingDelete(null);
      await cargar();
    } catch (cause) {
      push(cause instanceof Error ? cause.message : "No se pudo eliminar el modelo.", "danger");
    } finally {
      setDeleting(false);
    }
  };

  const filtro = (
    <div className="field" style={{ minWidth: 180 }}>
      <label className="field-label" htmlFor="filtro-instrumento">
        Instrumento
      </label>
      <select
        id="filtro-instrumento"
        className="select"
        value={instrumento}
        onChange={(event) => setInstrumento(event.target.value)}
      >
        <option value="all">Todos</option>
        {instrumentos.map((spec) => (
          <option key={spec.symbol} value={spec.symbol}>
            {spec.symbol}
          </option>
        ))}
      </select>
    </div>
  );

  return (
    <div className="stack">
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: "var(--s-4)",
          flexWrap: "wrap",
        }}
      >
        <Tabs
          label="Vista de modelos"
          value={vista}
          onChange={setVista}
          tabs={[
            { value: "models", label: "Modelos entrenados" },
            { value: "ranking", label: "Último ranking" },
          ]}
        />
        {filtro}
      </div>

      {vista === "models" && (
        <div className="stack" id="panel-models" role="tabpanel" aria-labelledby="tab-models">
          <ReadoutRow label="Registro de modelos">
            <Readout
              label="Modelos"
              value={modelos === null ? "—" : modelosVisibles.length}
              loading={modelos === null}
              note={instrumento === "all" ? "Entrenados en total" : `Para ${instrumento}`}
            />
            <Readout
              label="Instrumentos armados"
              value={parejasActivas.length}
              loading={modelos === null}
              note="Con modelo activo"
            />
          </ReadoutRow>

          <div className="stack">
            <Panel
              label="Activo por instrumento"
              bleed={parejasActivas.length === 0}
              caption="Cada instrumento tiene su propio modelo activo: el tamaño de las órdenes se calcula con la ficha del activo con el que se entrenó."
            >
              {parejasActivas.length === 0 ? (
                <EmptyState
                  title="Ningún instrumento tiene modelo activo"
                  hint="Mientras siga así, FSRPPO no operará. Activa uno de la tabla de abajo o entrena uno nuevo."
                  action={
                    <Link href="/train" className="btn">
                      Ir a Entrenamiento
                    </Link>
                  }
                />
              ) : (
                <TableFrame>
                  <table>
                    <thead>
                      <tr>
                        <th>Instrumento</th>
                        <th>Modelo activo</th>
                        <th>Acción</th>
                      </tr>
                    </thead>
                    <tbody>
                      {parejasActivas.map(([simbolo, runId]) => (
                        <tr key={simbolo} className={simbolo === instrumentoActual ? "is-marked" : ""}>
                          <td>
                            <AssetBadge symbol={simbolo} size="sm" showType={true} />
                            {simbolo === instrumentoActual && (
                              <div style={{ color: "var(--ink-3)", fontSize: "var(--fs-2xs)", marginTop: "2px" }}>
                                El que opera el bot
                              </div>
                            )}
                          </td>
                          <td className="mono">{runId}</td>
                          <td>
                            <button className="btn quiet" onClick={() => desactivar(simbolo)}>
                              Desactivar
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableFrame>
              )}
            </Panel>
          </div>

          <Panel
            label="Modelos entrenados"
            count={modelosVisibles.length}
            bleed
            caption="Las siete métricas son las de la Tabla 2 del paper, medidas sobre el tramo de test. El color compara cada modelo con su propio Buy & Hold: verde es mejor que comprar y mantener, rojo peor."
          >
            {modelos === null ? (
              <div style={{ padding: "var(--s-4)" }}>
                <Skeleton height={24} count={4} />
              </div>
            ) : modelosVisibles.length === 0 ? (
              <EmptyState
                title={
                  lista.length === 0
                    ? "Todavía no hay ningún modelo entrenado"
                    : "No hay modelos para este instrumento"
                }
                hint={
                  lista.length === 0
                    ? "Un modelo se entrena sobre un histórico descargado y queda ligado al instrumento y al reloj con los que se entrenó."
                    : "Cambia el filtro de instrumento o entrena uno para este símbolo."
                }
                action={
                  <Link href="/train" className="btn">
                    Entrenar un modelo
                  </Link>
                }
              />
            ) : (
              <TableFrame>
                <table>
                  <MetricsHead
                    first="Modelo (test)"
                    lead={["Instrumento", "TF"]}
                    extra={["Ops", "Acciones"]}
                  />
                  <tbody>
                    {modelosVisibles.map((m) => (
                      <Fragment key={m.run_id}>
                        <MetricsRow
                          name={
                            <button
                              className="btn quiet"
                              style={{ padding: 0, fontFamily: "var(--font-mono)" }}
                              onClick={() => setDetalle(detalle === m.run_id ? null : m.run_id)}
                              aria-expanded={detalle === m.run_id}
                              title="Ver los hiperparámetros y los tramos"
                            >
                              {m.is_active && <Icon name="star" size={12} />}
                              {m.run_id}
                            </button>
                          }
                          metrics={m.test_metrics}
                          reference={m.benchmark_metrics}
                          highlight={!!m.is_active}
                          lead={[
                            <AssetBadge key="sym" symbol={m.instrument} size="sm" showType={true} />,
                            m.timeframe?.toUpperCase() ?? "—",
                          ]}
                          extra={[
                            m.test_metrics?.trades ?? "—",
                            <span key="a" style={{ display: "flex", gap: "var(--s-1)" }}>
                              {!m.is_active && (
                                <button className="btn" onClick={() => activar(m.run_id)}>
                                  Activar
                                </button>
                              )}
                              <button
                                className="btn quiet"
                                onClick={() => comparar(m.run_id)}
                                disabled={comparando === m.run_id}
                              >
                                {comparando === m.run_id ? "Comparando…" : "Comparar"}
                              </button>
                              <button
                                className="btn quiet danger"
                                onClick={() => setPendingDelete(m.run_id)}
                                aria-label={`Eliminar modelo ${m.run_id}`}
                              >
                                <Icon name="trash" size={13} />
                              </button>
                            </span>,
                          ]}
                        />
                        {detalle === m.run_id && (
                          <tr>
                            <td colSpan={12} style={{ background: "var(--panel-inset)" }}>
                              <div style={{ display: "grid", gap: "var(--s-4)", padding: "var(--s-3) 0" }}>
                                <div className="field-note">
                                  Entrenado el {isoShort(m.created_at)}
                                  {m.is_active && " · activo para su instrumento"}
                                  {!m.meets_acceptance && " · no validado"}
                                </div>
                                <TrainingParams model={m} />
                                <table>
                                  <MetricsHead first="Tramo" />
                                  <tbody>
                                    <MetricsRow name="Train" metrics={m.train_metrics} />
                                    <MetricsRow name="Test" metrics={m.test_metrics} />
                                    <MetricsRow name="Buy & Hold (test)" metrics={m.benchmark_metrics} />
                                  </tbody>
                                </table>
                                <p className="field-note">
                                  Una diferencia grande entre train y test es sobreajuste: el
                                  modelo recuerda el pasado en vez de haber aprendido algo.
                                </p>
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </TableFrame>
            )}
          </Panel>

          {comparativa && (
            <Panel
              label="Comparativa sobre el tramo de test"
              actions={
                comparativa.test_range ? (
                  <span className="field-note">
                    {comparativa.test_range[0]?.slice(0, 10)} →{" "}
                    {comparativa.test_range[1]?.slice(0, 10)}
                  </span>
                ) : undefined
              }
              bleed={comparativa.ok}
              caption={
                comparativa.ok
                  ? "FSRPPO y Buy & Hold se valoran a mercado en cada barra; las estrategias por regla solo registran capital al cerrar cada operación. Sobre esa curva a saltos la volatilidad no es comparable, así que su Sharpe, Calmar y Sortino se dejan vacíos en vez de publicar cifras que parecerían equivalentes sin serlo. CRR, máxima caída y número de operaciones sí son comparables."
                  : undefined
              }
            >
              {!comparativa.ok ? (
                <Notice tone="danger">{comparativa.error}</Notice>
              ) : (
                <TableFrame>
                  <table>
                    <MetricsHead first="Estrategia" extra={["Ops", "Valoración"]} />
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
                </TableFrame>
              )}
            </Panel>
          )}
        </div>
      )}

      {vista === "ranking" && (
        <div id="panel-ranking" role="tabpanel" aria-labelledby="tab-ranking">
          <Panel
            label="Ranking de validación"
            actions={
              seleccion?.created_at ? (
                <span className="field-note">{isoShort(seleccion.created_at)}</span>
              ) : undefined
            }
            bleed
            caption={
              seleccion?.ok ? (
                <>
                  El ranking usa exclusivamente el 20% de validación: Sharpe mediano entre
                  semillas y CRR superior a Buy &amp; Hold. El 20% de test se evalúa solo para la
                  combinación ganadora.
                  {seleccion.test && (
                    <>
                      {" "}
                      Resultado final: {seleccion.test.passed}/{seleccion.test.total} semillas
                      (mínimo {seleccion.test.required});
                      {seleccion.test.accepted ? " criterio aprobado." : " criterio no aprobado."}
                    </>
                  )}
                </>
              ) : undefined
            }
          >
            {cargandoRanking ? (
              <div style={{ padding: "var(--s-4)" }}>
                <Skeleton height={24} count={3} />
              </div>
            ) : !seleccion?.ok ? (
              <EmptyState
                title="Todavía no hay ningún barrido"
                hint={
                  seleccion?.error ??
                  "Un barrido entrena varias semillas por instrumento y temporalidad, y ordena las combinaciones por su Sharpe mediano en validación."
                }
              />
            ) : rankingVisible.length === 0 ? (
              <EmptyState title="No hay resultados para este instrumento" />
            ) : (
              <TableFrame>
                <table>
                  <thead>
                    <tr>
                      <th className="num">Puesto</th>
                      <th>Instrumento</th>
                      <th>TF</th>
                      <th className="num">Sharpe mediano</th>
                      <th className="num">CRR mediano</th>
                      <th className="num">CRR de B&amp;H</th>
                      <th>Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rankingVisible.map((row) => (
                      <tr
                        key={`${row.symbol}-${row.timeframe}`}
                        className={row.winner ? "is-marked" : ""}
                      >
                        <td className="num">{row.rank}</td>
                        <td>
                          <AssetBadge symbol={row.symbol} size="sm" showType={true} />
                          {row.winner && (
                            <span style={{ marginLeft: "var(--s-2)" }}>
                              <Mark tone="ok">Ganadora</Mark>
                            </span>
                          )}
                        </td>
                        <td>{row.timeframe.toUpperCase()}</td>
                        <td className="num">{row.validation.median_sharpe?.toFixed(3) ?? "—"}</td>
                        <td className="num">
                          {row.validation.median_crr == null
                            ? "—"
                            : `${(row.validation.median_crr * 100).toFixed(2)}%`}
                        </td>
                        <td className="num">
                          {row.validation.benchmark_crr == null
                            ? "—"
                            : `${(row.validation.benchmark_crr * 100).toFixed(2)}%`}
                        </td>
                        <td className={row.eligible ? "pos" : "muted"}>
                          {row.eligible ? "Supera a B&H" : "No supera a B&H"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableFrame>
            )}
          </Panel>
        </div>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Eliminar modelo"
        description={
          <>
            Se eliminará <strong>{pendingDelete}</strong> y sus pesos entrenados. Esta acción no se
            puede deshacer.
          </>
        }
        confirmLabel="Eliminar modelo"
        danger
        busy={deleting}
        onCancel={() => setPendingDelete(null)}
        onConfirm={borrar}
      />
    </div>
  );
}
