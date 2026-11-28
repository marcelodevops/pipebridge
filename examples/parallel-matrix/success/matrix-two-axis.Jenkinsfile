pipeline {
    agent any
    stages {
        stage('Cross-Matrix') {
            matrix {
                axes {
                    axis {
                        name 'OS'
                        values 'ubuntu-latest', 'macos-latest'
                    }
                    axis {
                        name 'NODE_VERSION'
                        values '18', '20'
                    }
                }
                excludes {
                    exclude {
                        axis {
                            name 'OS'
                            values 'macos-latest'
                        }
                        axis {
                            name 'NODE_VERSION'
                            values '18'
                        }
                    }
                }
                stages {
                    stage('Test Cell') {
                        steps {
                            sh 'echo "Testing on ${OS} with Node ${NODE_VERSION}"'
                        }
                    }
                }
            }
        }
    }
}
