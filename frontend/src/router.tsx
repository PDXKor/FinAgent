import {
  createRootRoute,
  createRoute,
  createRouter,
  type RouterHistory,
} from "@tanstack/react-router";

import Layout from "./App";
import { parseDataSearch, parseRunsSearch } from "./lib/search";
import DataViewer from "./pages/DataViewer";
import Ingestion from "./pages/Ingestion";

const rootRoute = createRootRoute({ component: Layout });

const ingestionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  validateSearch: parseRunsSearch,
  component: Ingestion,
});

const dataRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/data",
  validateSearch: parseDataSearch,
  component: DataViewer,
});

const routeTree = rootRoute.addChildren([ingestionRoute, dataRoute]);

/** Browser history by default; tests pass a memory history. */
export function makeRouter(history?: RouterHistory) {
  return createRouter({ routeTree, history });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof makeRouter>;
  }
}
