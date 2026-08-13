import { useEffect, useRef } from 'react'
import type { Config, Data, Layout } from 'plotly.js'

export function PlotlyFigure({
  data,
  layout,
  config,
}: {
  data: Data[]
  layout: Partial<Layout>
  config?: Partial<Config>
}) {
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const node = root.current
    let disposed = false
    let plotly: typeof import('plotly.js') | undefined
    void import('plotly.js-dist-min').then(module => {
      if (disposed || !node) return
      plotly = module.default
      void plotly.react(node, data, {
        autosize: true,
        paper_bgcolor: '#081421',
        plot_bgcolor: '#081421',
        font: { color: '#9fb2c6', family: 'Inter, sans-serif', size: 10 },
        margin: { l: 55, r: 25, t: 38, b: 48 },
        ...layout,
      }, { responsive: true, displaylogo: false, ...config })
    })
    return () => {
      disposed = true
      if (plotly && node) plotly.purge(node)
    }
  }, [config, data, layout])
  return <div ref={root} className="plotly-figure" />
}
