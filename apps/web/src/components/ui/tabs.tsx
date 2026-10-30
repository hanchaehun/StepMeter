// shadcn/ui Tabs (Radix). 선택된 탭은 밑줄 2px #171717 (조작 요소 경계 3:1 이상).
import * as TabsPrimitive from '@radix-ui/react-tabs';
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from 'react';
import { cn } from '@/lib/cn';

export const Tabs = TabsPrimitive.Root;

export const TabsList = forwardRef<ElementRef<typeof TabsPrimitive.List>, ComponentPropsWithoutRef<typeof TabsPrimitive.List>>(
  ({ className, ...props }, ref) => (
    <TabsPrimitive.List ref={ref} className={cn('flex gap-1 border-b border-border', className)} {...props} />
  ),
);
TabsList.displayName = 'TabsList';

export const TabsTrigger = forwardRef<ElementRef<typeof TabsPrimitive.Trigger>, ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>>(
  ({ className, ...props }, ref) => (
    <TabsPrimitive.Trigger
      ref={ref}
      className={cn(
        '-mb-px inline-flex min-h-[44px] items-center border-b-2 border-transparent px-4 text-sm font-semibold text-faint',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary',
        'data-[state=active]:border-primary data-[state=active]:text-fg disabled:opacity-40',
        className,
      )}
      {...props}
    />
  ),
);
TabsTrigger.displayName = 'TabsTrigger';

export const TabsContent = forwardRef<ElementRef<typeof TabsPrimitive.Content>, ComponentPropsWithoutRef<typeof TabsPrimitive.Content>>(
  ({ className, ...props }, ref) => <TabsPrimitive.Content ref={ref} className={cn('pt-6 focus-visible:outline-none', className)} {...props} />,
);
TabsContent.displayName = 'TabsContent';
