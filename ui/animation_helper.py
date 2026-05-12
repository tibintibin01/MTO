# -*- coding: utf-8 -*-
import time

class WidgetAnimator:
    """
    Helper to provide smooth visual transitions in CustomTkinter.
    Uses .after() to simulate property animations.
    """
    @staticmethod
    def fade_in(widget, duration=500, steps=20):
        """Gradually increases transparency (if supported) or just handles sequenced appearing."""
        # CustomTkinter doesn't support alpha on all widgets easily, 
        # so we simulate by placing and potentially sliding.
        pass

    @staticmethod
    def slide_up(widget, start_y, end_y, duration=400, steps=15):
        """Smoothly moves a widget from start_y to end_y."""
        distance = end_y - start_y
        step_distance = distance / steps
        step_time = int(duration / steps)
        
        def animate(current_step):
            if current_step <= steps:
                new_y = start_y + (step_distance * current_step)
                # Assuming the widget is placed via .place() or similar
                # For .pack(), we can use pady or just a spacer
                try:
                    # Generic move logic - might need refinement based on parent layout
                    info = widget.place_info()
                    if info:
                        widget.place(y=new_y)
                except:
                    pass
                widget.after(step_time, lambda: animate(current_step + 1))
        
        animate(1)

    @staticmethod
    def pulse(widget, original_color, highlight_color, duration=300):
        """Quickly flashes a widget's color to provide feedback."""
        widget.configure(fg_color=highlight_color)
        widget.after(duration, lambda: widget.configure(fg_color=original_color))
