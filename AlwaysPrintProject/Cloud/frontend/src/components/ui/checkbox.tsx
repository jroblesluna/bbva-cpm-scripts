"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * Componente Checkbox estilizado con Tailwind.
 * Compatible con el sistema de diseño shadcn/ui del proyecto.
 */

export interface CheckboxProps extends React.InputHTMLAttributes<HTMLInputElement> {
  indeterminate?: boolean;
}

const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, indeterminate, ...props }, ref) => {
    const internalRef = React.useRef<HTMLInputElement>(null);

    React.useEffect(() => {
      const element = (ref as React.RefObject<HTMLInputElement>)?.current ?? internalRef.current;
      if (element) {
        element.indeterminate = indeterminate ?? false;
      }
    }, [indeterminate, ref]);

    return (
      <input
        type="checkbox"
        className={cn(
          "h-4 w-4 shrink-0 rounded border border-primary ring-offset-background",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          "disabled:cursor-not-allowed disabled:opacity-50",
          "accent-primary cursor-pointer",
          className
        )}
        ref={ref ?? internalRef}
        {...props}
      />
    );
  }
);
Checkbox.displayName = "Checkbox";

export { Checkbox };
