import { Component } from 'react'
import Icon from './Icon'

// Keeps a rendering bug in one pane from blanking the whole app. Resets
// when `resetKey` changes (i.e. a different document is selected).
export default class ErrorBoundary extends Component {
  state = { error: null, resetKey: this.props.resetKey }

  static getDerivedStateFromError(error) {
    return { error }
  }

  static getDerivedStateFromProps(props, state) {
    if (props.resetKey !== state.resetKey) return { error: null, resetKey: props.resetKey }
    return null
  }

  componentDidCatch(error, info) {
    console.error('Detail pane crashed:', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="banner banner-red detail-crash">
        <Icon name="alert" size={20} />
        <div>
          <h3>This document couldn’t be displayed</h3>
          <p>{String(this.state.error.message || this.state.error)}</p>
        </div>
      </div>
    )
  }
}
