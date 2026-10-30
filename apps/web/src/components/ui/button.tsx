// shadcn/ui Button을 이 프로젝트 토큰에 맞춰 줄인 것. 모든 variant가 min-height 44px (자체 UX 기준).
import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/cn';

const buttonVariants = cva(
  'inline-flex min-h-[44px] items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-40',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-fg hover:bg-primary/90',
        outline: 'border border-control bg-bg text-fg hover:bg-surface',
        ghost: 'text-fg hover:bg-surface',
        link: 'text-fg underline-offset-4 hover:underline px-1',
      },
      size: {
        default: 'px-4',
        icon: 'h-11 w-11 px-0',
      },
    },
    defaultVariants: { variant: 'outline', size: 'default' },
  },
);

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, type = 'button', ...props }, ref) => (
  <button ref={ref} type={type} className={cn(buttonVariants({ variant, size }), className)} {...props} />
));
Button.displayName = 'Button';
