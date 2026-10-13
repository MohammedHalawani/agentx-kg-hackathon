import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
  type PaginationState,
  type OnChangeFn,
} from "@tanstack/react-table";
import { motion, AnimatePresence } from "motion/react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
} from "@/components/ui/pagination";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
} from "@/components/ui/empty";
import { SelectControl } from "@/components/select-control";
import { usePreferences } from "@/state/preferences";

export function DataTable<T>({
  columns,
  data,
  rowId,
  onRowClick,
  pagination,
  onPaginationChange,
  total,
  manualPagination = false,
  emptyTitle,
  emptyDescription,
  animate = false,
}: {
  columns: ColumnDef<T>[];
  data: T[];
  rowId: (row: T) => string;
  onRowClick?: (row: T) => void;
  pagination: PaginationState;
  onPaginationChange: OnChangeFn<PaginationState>;
  total?: number;
  manualPagination?: boolean;
  emptyTitle: string;
  emptyDescription: string;
  animate?: boolean;
}) {
  const { t } = usePreferences();
  const table = useReactTable({
    data,
    columns,
    getRowId: rowId,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    // Filter controls explicitly reset pagination; derived row arrays must not
    // trigger TanStack's automatic reset on every parent render.
    autoResetPageIndex: false,
    onPaginationChange,
    manualPagination,
    rowCount: total,
    state: { pagination },
  });
  const count = total ?? data.length;
  const pageCount = Math.max(1, table.getPageCount());
  const rows = table.getRowModel().rows;
  return (
    <>
      <Table className="domain-data-table">
        <TableHeader>
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id}>
              {group.headers.map((header) => (
                <TableHead key={header.id} style={{ width: header.getSize() }}>
                  {header.isPlaceholder
                    ? null
                    : flexRender(
                        header.column.columnDef.header,
                        header.getContext(),
                      )}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          <AnimatePresence initial={false}>
            {rows.map((row) => (
              <motion.tr
                key={row.id}
                layout={animate ? "position" : false}
                initial={animate ? { opacity: 0, y: 4 } : false}
                animate={{ opacity: 1, y: 0 }}
                exit={animate ? { opacity: 0, x: 16 } : undefined}
                className={`data-row ${onRowClick ? "clickable" : ""}`}
                data-testid={`data-row-${row.id}`}
                onClick={(e) => {
                  if (
                    !(e.target as HTMLElement).closest(
                      "a,button,input,[role=combobox]",
                    )
                  )
                    onRowClick?.(row.original);
                }}
              >
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </motion.tr>
            ))}
          </AnimatePresence>
        </TableBody>
      </Table>
      {rows.length === 0 && (
        <Empty className="py-16">
          <EmptyHeader>
            <EmptyTitle className="text-sm">{emptyTitle}</EmptyTitle>
            <EmptyDescription className="text-xs">
              {emptyDescription}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}
      <div className="table-footer">
        <span>
          {t(
            `Showing ${count === 0 ? 0 : pagination.pageIndex * pagination.pageSize + 1}–${Math.min((pagination.pageIndex + 1) * pagination.pageSize, count)} of ${count}`,
            `عرض ${count === 0 ? 0 : pagination.pageIndex * pagination.pageSize + 1}–${Math.min((pagination.pageIndex + 1) * pagination.pageSize, count)} من ${count}`,
          )}
        </span>
        <div>
          <span className="rows-label">{t("Rows", "الصفوف")}</span>
          <SelectControl
            label="Rows per page"
            value={String(pagination.pageSize)}
            onChange={(v) => table.setPageSize(Number(v))}
            options={[
              { value: "10", label: "10" },
              { value: "25", label: "25" },
              { value: "50", label: "50" },
            ]}
            className="rows-select"
          />
          <Pagination className="w-auto">
            <PaginationContent>
              <PaginationItem>
                <Button
                  aria-label="Previous table page"
                  variant="outline"
                  size="icon-sm"
                  disabled={!table.getCanPreviousPage()}
                  onClick={() => table.previousPage()}
                >
                  <ChevronLeft size={14} />
                </Button>
              </PaginationItem>
              <PaginationItem>
                <span className="page-index">
                  {Math.min(pagination.pageIndex + 1, pageCount)} / {pageCount}
                </span>
              </PaginationItem>
              <PaginationItem>
                <Button
                  aria-label="Next table page"
                  variant="outline"
                  size="icon-sm"
                  disabled={!table.getCanNextPage()}
                  onClick={() => table.nextPage()}
                >
                  <ChevronRight size={14} />
                </Button>
              </PaginationItem>
            </PaginationContent>
          </Pagination>
        </div>
      </div>
    </>
  );
}
