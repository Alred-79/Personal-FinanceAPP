import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

describe('Smoke Test', () => {
  it('renders a simple component', () => {
    const TestComponent = () => <div>Hello, World!</div>;
    render(<TestComponent />);
    expect(screen.getByText('Hello, World!')).toBeInTheDocument();
  });
});
