package io.github.bkonold.prbrief.diff

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class StepStopTest {
    @Test
    fun stepsToTheNeighbouringStop() {
        assertEquals(3, stepStop(2, 6, 1))
        assertEquals(1, stepStop(2, 6, -1))
    }

    @Test
    fun stopsAtEitherEnd() {
        assertNull(stepStop(0, 6, -1))
        assertNull(stepStop(5, 6, 1))
    }

    @Test
    fun startsAtTheFirstOrLastStopWhenNoneIsSelected() {
        assertEquals(0, stepStop(null, 6, 1))
        assertEquals(5, stepStop(null, 6, -1))
    }

    @Test
    fun hasNowhereToGoInAnEmptyWalkthrough() {
        assertNull(stepStop(null, 0, 1))
        assertNull(stepStop(null, 0, -1))
    }
}
