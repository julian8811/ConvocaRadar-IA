declare module 'react-plotly.js' {
  import { ComponentType } from 'react';

  interface PlotParams {
    data: object[];
    layout?: object;
    config?: object;
    className?: string;
    useResizeHandler?: boolean;
    style?: object;
    onInitialized?: (figure: object, gd: object) => void;
    onUpdate?: (figure: object, gd: object) => void;
    onPurge?: (figure: object, gd: object) => void;
    onError?: (err: Error) => void;
  }

  const Plot: ComponentType<PlotParams>;
  export default Plot;
}
